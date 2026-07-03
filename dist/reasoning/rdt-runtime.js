import { AttentionMoEManager } from './attention.js';
import { ConfidenceEvaluator } from './confidence.js';
function nowMs() {
    return Date.now();
}
function truncateText(text, maxChars) {
    if (text.length <= maxChars)
        return text;
    return `${text.slice(0, Math.max(0, maxChars - 3))}...`;
}
function tryParseJson(raw) {
    try {
        return JSON.parse(raw);
    }
    catch {
        return null;
    }
}
function extractJsonObject(raw) {
    const start = raw.indexOf('{');
    const end = raw.lastIndexOf('}');
    if (start < 0 || end <= start)
        return null;
    return raw.slice(start, end + 1);
}
export class RDTRuntime {
    deps;
    attentionManager;
    confidenceEvaluator;
    constructor(deps) {
        this.deps = deps;
        this.attentionManager = new AttentionMoEManager(deps.config.attention);
        this.confidenceEvaluator = new ConfidenceEvaluator(deps.config.confidence);
    }
    async run(input) {
        const state = {
            stage: 'prelude',
            prompt: input.prompt,
            decomposition: [],
            trace: [],
            haltedEarly: false,
            metadata: { ...(input.metadata ?? {}) }
        };
        const preludeStart = nowMs();
        await this.emit({ type: 'rdt_stage_started', stage: 'prelude' });
        const preludeRaw = await this.invokeStage({
            stage: 'prelude',
            prompt: this.buildPreludePrompt(input),
            temperature: this.deps.config.prelude.temperature,
            maxTokens: this.deps.config.prelude.maxTokens,
            metadata: { mode: 'decomposition' }
        });
        const prelude = this.parsePayload(preludeRaw, input.prompt);
        state.decomposition = prelude.decomposition;
        await this.emit({ type: 'rdt_stage_completed', stage: 'prelude', latencyMs: nowMs() - preludeStart });
        const maxLoopIters = Math.min(this.deps.config.loop.maxLoopIters, this.deps.config.recurrent.maxLoopIters);
        const minLoopIters = Math.max(this.deps.config.loop.minLoopIters, this.deps.config.recurrent.minLoopIters);
        let revisionCount = 0;
        for (let iteration = 1; iteration <= maxLoopIters; iteration += 1) {
            state.stage = 'recurrent';
            if (iteration === 1) {
                await this.emit({ type: 'rdt_stage_started', stage: 'recurrent' });
            }
            const prior = state.trace[state.trace.length - 1];
            const attention = this.attentionManager.decide({
                prompt: input.prompt,
                decomposition: state.decomposition,
                iteration,
                previous: prior
            });
            const recurrentPayload = await this.runRecurrentIteration({
                input,
                state,
                iteration,
                attention
            });
            const confidence = this.confidenceEvaluator.evaluate(recurrentPayload.summary, prior, state.decomposition);
            let current = {
                iteration,
                summary: recurrentPayload.summary,
                reasoning: recurrentPayload.reasoning,
                confidence: confidence.confidence,
                confidenceThreshold: confidence.threshold,
                attentionMode: attention.mode,
                routedExperts: attention.routedExperts,
                sharedExperts: attention.sharedExperts,
                quality: confidence.metrics
            };
            if (this.deps.config.recurrent.allowBacktracking &&
                prior &&
                prior.confidence - current.confidence >= 0.12 &&
                revisionCount < this.deps.config.loop.maxRevisionDepth) {
                revisionCount += 1;
                current = {
                    ...prior,
                    iteration,
                    revisedFromIteration: prior.iteration
                };
                await this.emit({
                    type: 'rdt_backtrack',
                    iteration,
                    fromConfidence: confidence.confidence,
                    toConfidence: current.confidence,
                    reason: 'confidence_regression'
                });
            }
            state.trace.push(current);
            if (!state.bestIteration || current.confidence > state.bestIteration.confidence) {
                state.bestIteration = current;
            }
            await this.emit({
                type: 'rdt_iteration_completed',
                iteration,
                confidence: current.confidence,
                threshold: current.confidenceThreshold,
                attentionMode: current.attentionMode,
                routedExperts: current.routedExperts,
                quality: current.quality
            });
            await this.emit({ type: 'rdt_quality', iteration, quality: current.quality });
            if (this.deps.config.quality.enableTraceLogging) {
                await this.emit({
                    type: 'rdt_trace',
                    message: 'iteration_trace',
                    data: {
                        iteration,
                        decomposition: state.decomposition,
                        confidenceExplanation: current.quality.explanation,
                        expertLoads: this.attentionManager.snapshotLoads()
                    }
                });
            }
            if (iteration >= minLoopIters && confidence.shouldExit) {
                state.haltedEarly = true;
                await this.emit({
                    type: 'rdt_early_exit',
                    iteration,
                    confidence: current.confidence,
                    threshold: current.confidenceThreshold,
                    reason: 'confidence_threshold_met'
                });
                break;
            }
        }
        await this.emit({ type: 'rdt_stage_completed', stage: 'recurrent', latencyMs: 0 });
        state.stage = 'coda';
        const codaStart = nowMs();
        await this.emit({ type: 'rdt_stage_started', stage: 'coda' });
        const codaPrompt = this.buildCodaPrompt(input, state);
        const finalTextRaw = await this.invokeStage({
            stage: 'coda',
            prompt: codaPrompt,
            temperature: this.deps.config.coda.temperature,
            maxTokens: this.deps.config.coda.maxTokens,
            metadata: { loopsUsed: state.trace.length }
        });
        const maxOutput = input.tokenBudget?.maxOutputChars;
        state.finalAnswer = typeof maxOutput === 'number' ? truncateText(finalTextRaw, maxOutput) : finalTextRaw;
        await this.emit({ type: 'rdt_stage_completed', stage: 'coda', latencyMs: nowMs() - codaStart });
        const quality = this.aggregateQuality(state.trace);
        return {
            finalText: state.finalAnswer,
            loopsUsed: state.trace.length,
            finalConfidence: state.bestIteration?.confidence ?? 0,
            haltedEarly: state.haltedEarly,
            trace: state.trace,
            quality
        };
    }
    async runRecurrentIteration(args) {
        const { input, state, iteration, attention } = args;
        if (this.shouldRunParallelPaths(iteration, state.decomposition)) {
            const pathA = this.invokeStage({
                stage: 'recurrent',
                prompt: this.buildRecurrentPrompt(input, state, iteration, attention, 'exploit'),
                temperature: this.deps.config.recurrent.temperature,
                maxTokens: this.deps.config.recurrent.maxTokens,
                metadata: { path: 'exploit' }
            });
            const pathB = this.invokeStage({
                stage: 'recurrent',
                prompt: this.buildRecurrentPrompt(input, state, iteration, attention, 'explore'),
                temperature: Math.min(0.6, this.deps.config.recurrent.temperature + 0.08),
                maxTokens: this.deps.config.recurrent.maxTokens,
                metadata: { path: 'explore' }
            });
            const [a, b] = await Promise.all([pathA, pathB]);
            const parsedA = this.parsePayload(a, state.prompt);
            const parsedB = this.parsePayload(b, state.prompt);
            const pickA = parsedA.summary.length >= parsedB.summary.length;
            await this.emit({
                type: 'rdt_parallel_path',
                iteration,
                selectedPath: pickA ? 'exploit' : 'explore',
                candidatePaths: ['exploit', 'explore']
            });
            return pickA ? parsedA : parsedB;
        }
        const recurrentRaw = await this.invokeStage({
            stage: 'recurrent',
            prompt: this.buildRecurrentPrompt(input, state, iteration, attention, 'single'),
            temperature: this.deps.config.recurrent.temperature,
            maxTokens: this.deps.config.recurrent.maxTokens,
            metadata: { path: 'single' }
        });
        return this.parsePayload(recurrentRaw, state.prompt);
    }
    shouldRunParallelPaths(iteration, decomposition) {
        return this.deps.config.recurrent.allowParallelPaths && this.deps.config.quality.enableMultiHop && decomposition.length >= 3 && iteration <= 2;
    }
    buildPreludePrompt(input) {
        const contextBlock = (input.context ?? []).slice(-5).join('\n');
        const maxInput = input.tokenBudget?.maxInputChars;
        const prompt = typeof maxInput === 'number' ? truncateText(input.prompt, maxInput) : input.prompt;
        return [
            this.deps.config.prelude.systemInstruction,
            'Decompose the user problem into explicit steps and produce a latent summary.',
            'Return strict JSON with keys: summary (string), decomposition (string[]), reasoning (string[]).',
            `Prompt: ${prompt}`,
            contextBlock ? `Recent context:\n${contextBlock}` : undefined
        ]
            .filter(Boolean)
            .join('\n');
    }
    buildRecurrentPrompt(input, state, iteration, attention, path) {
        const lastTrace = state.trace[state.trace.length - 1];
        const reasoningHistory = this.deps.config.quality.preserveReasoningChain
            ? state.trace.map((entry) => `iter=${entry.iteration} confidence=${entry.confidence.toFixed(2)} summary=${entry.summary}`).join('\n')
            : 'disabled';
        return [
            this.deps.config.recurrent.systemInstruction,
            `Iteration: ${iteration}`,
            `Attention mode: ${attention.mode}`,
            `Routed experts: ${attention.routedExperts.join(', ') || 'none'}`,
            `Shared experts: ${attention.sharedExperts.join(', ') || 'none'}`,
            `Path strategy: ${path}`,
            `Task decomposition: ${state.decomposition.join(' | ') || 'none'}`,
            `Previous summary: ${lastTrace?.summary ?? state.prompt}`,
            `Reasoning chain:\n${reasoningHistory}`,
            `User prompt: ${input.prompt}`,
            'Refine the reasoning. If evidence is weak, propose revision points and continue.',
            'Return strict JSON with keys: summary (string), decomposition (string[]), reasoning (string[]).'
        ].join('\n');
    }
    buildCodaPrompt(input, state) {
        const best = state.bestIteration ?? state.trace[state.trace.length - 1];
        return [
            this.deps.config.coda.systemInstruction,
            'Synthesize the final answer from the best recurrent iteration.',
            `User prompt: ${input.prompt}`,
            `Best summary: ${best?.summary ?? ''}`,
            `Best confidence: ${(best?.confidence ?? 0).toFixed(2)}`,
            `Reasoning checkpoints: ${state.trace.map((t) => `[${t.iteration}:${t.confidence.toFixed(2)}]`).join(' ')}`,
            'Return plain text answer only. Avoid JSON in coda output.'
        ].join('\n');
    }
    parsePayload(raw, fallbackPrompt) {
        const fromRaw = tryParseJson(raw) ?? (extractJsonObject(raw) ? tryParseJson(extractJsonObject(raw) ?? '') : null);
        if (fromRaw) {
            return {
                summary: (fromRaw.summary || fallbackPrompt).trim(),
                decomposition: Array.isArray(fromRaw.decomposition) ? fromRaw.decomposition.map((entry) => String(entry)).slice(0, 10) : [],
                reasoning: Array.isArray(fromRaw.reasoning) ? fromRaw.reasoning.map((entry) => String(entry)).slice(0, 10) : []
            };
        }
        return {
            summary: raw.trim() || fallbackPrompt,
            decomposition: [],
            reasoning: []
        };
    }
    async invokeStage(args) {
        let out = '';
        for await (const delta of this.deps.invoke({
            stage: args.stage,
            prompt: args.prompt,
            temperature: args.temperature,
            maxTokens: args.maxTokens,
            metadata: args.metadata
        })) {
            out += delta;
            if (args.stage !== 'recurrent') {
                await this.emit({ type: 'rdt_output_delta', stage: args.stage, text: delta });
            }
        }
        return out.trim();
    }
    aggregateQuality(trace) {
        if (trace.length === 0) {
            return {
                avgCoherence: 0,
                avgCompleteness: 0,
                avgConsistency: 0,
                avgAggregate: 0
            };
        }
        const totals = trace.reduce((acc, iteration) => {
            acc.coherence += iteration.quality.coherence;
            acc.completeness += iteration.quality.completeness;
            acc.consistency += iteration.quality.consistency;
            acc.aggregate += iteration.quality.aggregate;
            return acc;
        }, { coherence: 0, completeness: 0, consistency: 0, aggregate: 0 });
        return {
            avgCoherence: totals.coherence / trace.length,
            avgCompleteness: totals.completeness / trace.length,
            avgConsistency: totals.consistency / trace.length,
            avgAggregate: totals.aggregate / trace.length
        };
    }
    async emit(event) {
        await this.deps.emit?.(event);
    }
}
//# sourceMappingURL=rdt-runtime.js.map