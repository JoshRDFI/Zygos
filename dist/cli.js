#!/usr/bin/env node
import { createEngine } from './core/bootstrap.js';
async function main() {
    const args = process.argv.slice(2);
    const configFlagIndex = args.indexOf('--config');
    const providerFlagIndex = args.indexOf('--provider');
    const modelFlagIndex = args.indexOf('--model');
    const historySearchIndex = args.indexOf('--history-search');
    const sessionFlagIndex = args.indexOf('--session');
    const rdtFlagIndex = args.indexOf('--rdt');
    const rdtProfileFlagIndex = args.indexOf('--rdt-profile');
    const learningListIndex = args.indexOf('--learning-list');
    const learningApplyIndex = args.indexOf('--learning-apply');
    const learningRollbackIndex = args.indexOf('--learning-rollback');
    const learningMetricsIndex = args.indexOf('--learning-metrics');
    const interviewFlagIndex = args.indexOf('--interview');
    const interviewActionIndex = args.indexOf('--interview-action');
    const stakeholderIndex = args.indexOf('--stakeholder');
    const interviewOverrideIndex = args.indexOf('--interview-override');
    const configPath = configFlagIndex >= 0 ? args[configFlagIndex + 1] : undefined;
    const providerOverride = providerFlagIndex >= 0 ? args[providerFlagIndex + 1] : undefined;
    const modelOverride = modelFlagIndex >= 0 ? args[modelFlagIndex + 1] : undefined;
    const historyQuery = historySearchIndex >= 0 ? args[historySearchIndex + 1] : undefined;
    const explicitSession = sessionFlagIndex >= 0 ? args[sessionFlagIndex + 1] : undefined;
    const rdtEnabledRaw = rdtFlagIndex >= 0 ? args[rdtFlagIndex + 1] : undefined;
    const rdtProfile = rdtProfileFlagIndex >= 0 ? args[rdtProfileFlagIndex + 1] : undefined;
    const learningApplyId = learningApplyIndex >= 0 ? args[learningApplyIndex + 1] : undefined;
    const learningRollbackTarget = learningRollbackIndex >= 0 ? args[learningRollbackIndex + 1] : undefined;
    const hasLearningList = learningListIndex >= 0;
    const hasLearningMetrics = learningMetricsIndex >= 0;
    const hasInterviewMode = interviewFlagIndex >= 0;
    const interviewAction = interviewActionIndex >= 0 ? args[interviewActionIndex + 1] : undefined;
    const stakeholderId = stakeholderIndex >= 0 ? args[stakeholderIndex + 1] : undefined;
    const interviewOverride = interviewOverrideIndex >= 0;
    const stripped = new Set();
    const pushFlagIndices = (index, hasValue = true) => {
        if (index >= 0) {
            stripped.add(index);
            if (hasValue) {
                stripped.add(index + 1);
            }
        }
    };
    pushFlagIndices(configFlagIndex);
    pushFlagIndices(providerFlagIndex);
    pushFlagIndices(modelFlagIndex);
    pushFlagIndices(historySearchIndex);
    pushFlagIndices(sessionFlagIndex);
    pushFlagIndices(rdtFlagIndex);
    pushFlagIndices(rdtProfileFlagIndex);
    pushFlagIndices(learningListIndex, false);
    pushFlagIndices(learningApplyIndex);
    pushFlagIndices(learningRollbackIndex);
    pushFlagIndices(learningMetricsIndex, false);
    pushFlagIndices(interviewFlagIndex, false);
    pushFlagIndices(interviewActionIndex);
    pushFlagIndices(stakeholderIndex);
    pushFlagIndices(interviewOverrideIndex, false);
    const userMessage = args
        .filter((_, i) => !stripped.has(i))
        .join(' ')
        .trim();
    if (!userMessage && !historyQuery && !hasLearningList && !learningApplyId && !learningRollbackTarget && !hasLearningMetrics && !hasInterviewMode) {
        console.error('Usage: npm run dev -- "<message>" [--config path/to/config.yaml] [--provider openai] [--model gpt-4o-mini] [--session session_id] [--rdt true|false] [--rdt-profile shallow|balanced|deep] [--learning-list] [--learning-apply proposal_id] [--learning-rollback tool[:versionId]] [--learning-metrics] [--interview --interview-action start|answer|complete|status|plan_export --stakeholder stakeholder_id --interview-override] OR --history-search "query" --session session_id');
        process.exitCode = 1;
        return;
    }
    const normalizedRdtEnabled = typeof rdtEnabledRaw === 'string'
        ? ['1', 'true', 'on', 'yes', 'enabled'].includes(rdtEnabledRaw.toLowerCase())
        : undefined;
    const engine = await createEngine(configPath, {
        provider: providerOverride,
        model: modelOverride,
        rdtEnabled: normalizedRdtEnabled,
        rdtProfile: rdtProfile
    });
    if (hasLearningList) {
        const proposals = await engine.listLearningProposals?.();
        for (const proposal of proposals ?? []) {
            console.log(`[learning:proposal] id=${proposal.id} kind=${proposal.kind} status=${proposal.status} risk=${proposal.risk}`);
        }
        return;
    }
    if (learningApplyId) {
        await engine.applyLearningProposal?.(learningApplyId, 'cli');
        console.log(`[learning:applied] id=${learningApplyId}`);
        return;
    }
    if (learningRollbackTarget) {
        const [toolName, versionText] = learningRollbackTarget.split(':');
        const version = versionText ? Number(versionText) : undefined;
        await engine.rollbackLearnedTool?.(toolName, Number.isFinite(version) ? version : undefined, 'cli');
        console.log(`[learning:rollback] tool=${toolName} version=${version ?? 'previous'}`);
        return;
    }
    if (hasLearningMetrics) {
        const metrics = await engine.getLearningMetrics?.();
        console.log(`[learning:metrics] ${JSON.stringify(metrics ?? {}, null, 2)}`);
        return;
    }
    if (historyQuery) {
        if (!explicitSession) {
            console.error('History search requires --session <session_id>.');
            process.exitCode = 1;
            return;
        }
        const hits = await engine.searchHistory?.({
            sessionId: explicitSession,
            query: historyQuery,
            includeSnippets: true,
            limit: 10
        });
        for (const hit of hits ?? []) {
            console.log(`[history] rank=${hit.rank.toFixed(4)} speaker=${hit.turn.speaker} snippet=${hit.snippet ?? hit.turn.content}`);
        }
        return;
    }
    const sessionId = explicitSession ?? `session_${Date.now()}`;
    const stream = engine.runTurn({
        sessionId,
        userMessage: userMessage || 'Start interview',
        mode: hasInterviewMode ? 'interview' : 'standard',
        interview: hasInterviewMode
            ? {
                action: interviewAction ?? 'answer',
                stakeholderId,
                overrideGating: interviewOverride
            }
            : undefined
    });
    for await (const event of stream) {
        switch (event.type) {
            case 'state_changed':
                console.log(`[state] ${event.from} -> ${event.to}`);
                break;
            case 'provider_selected':
                console.log(`[provider] ${event.route.provider}:${event.route.model}`);
                break;
            case 'retry_scheduled':
                console.log(`[retry] delay=${event.delayMs}ms reason=${event.reason}`);
                break;
            case 'fallback_activated':
                console.log(`[fallback] ${event.route.provider}:${event.route.model}`);
                break;
            case 'model_delta':
                process.stdout.write(event.text);
                break;
            case 'rdt_progress':
                if (event.event.type === 'rdt_iteration_completed') {
                    console.log(`\n[rdt] iter=${event.event.iteration} conf=${event.event.confidence.toFixed(2)} thr=${event.event.threshold.toFixed(2)} mode=${event.event.attentionMode}`);
                }
                else if (event.event.type === 'rdt_early_exit') {
                    console.log(`\n[rdt] early-exit iter=${event.event.iteration} conf=${event.event.confidence.toFixed(2)} reason=${event.event.reason}`);
                }
                else if (event.event.type === 'rdt_parallel_path') {
                    console.log(`\n[rdt] parallel selected=${event.event.selectedPath} candidates=${event.event.candidatePaths.join(',')}`);
                }
                break;
            case 'rdt_observability':
                console.log(`\n[rdt:metrics] loops=${event.metrics.loopsUsed} early=${event.metrics.haltedEarly} conf=${event.metrics.finalConfidence.toFixed(2)} quality=${event.metrics.avgAggregateQuality.toFixed(2)}`);
                break;
            case 'tool_started':
                console.log(`\n[tool:start] ${event.call.name}`);
                break;
            case 'tool_progress':
                console.log(`\n[tool:progress] id=${event.event.toolCallId} message=${event.event.message ?? 'update'}`);
                break;
            case 'tool_timeout':
                console.log(`\n[tool:timeout] ${event.call.name} elapsed=${event.elapsedMs}ms`);
                break;
            case 'tool_completed':
                console.log(`\n[tool:done] ok=${event.result.ok} output=${JSON.stringify(event.result.output)} error=${event.result.error ?? ''}`);
                break;
            case 'tool_batch_completed':
                console.log(`\n[tool:batch] count=${event.results.length}`);
                break;
            case 'learning_cycle':
                console.log(`\n[learning] proposals=${event.proposals} applied=${event.applied}`);
                break;
            case 'learning_applied':
                console.log(`\n[learning:applied] id=${event.proposalId} kind=${event.kind}`);
                break;
            case 'interview_progress':
                if (event.response.nextQuestion) {
                    console.log(`\n[interview:question] ${event.response.nextQuestion.text}`);
                }
                else {
                    console.log(`\n[interview] done=${event.response.done}`);
                }
                break;
            case 'interview_plan_generated':
                console.log(`\n[interview:plan] id=${event.planId} complexity=${event.complexity} effort=${event.estimatedEffortHours}h`);
                break;
            case 'interview_metrics':
                console.log(`\n[interview:metrics] ${JSON.stringify(event.metrics)}`);
                break;
            case 'turn_completed':
                console.log(`\n[done] chars=${event.result.usage.outputChars}`);
                break;
            case 'turn_failed':
                console.error(`\n[failed] ${event.error.code}: ${event.error.message}`);
                break;
            default:
                break;
        }
    }
}
main().catch((error) => {
    console.error('[fatal]', error);
    process.exitCode = 1;
});
//# sourceMappingURL=cli.js.map