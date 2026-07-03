export type RDTStageName = 'prelude' | 'recurrent' | 'coda';
export type AttentionMode = 'mla' | 'gqa' | 'auto';
export type ReasoningDepthProfile = 'shallow' | 'balanced' | 'deep';
export interface StageConfig {
    enabled: boolean;
    temperature: number;
    maxTokens?: number;
    systemInstruction: string;
}
export interface RecurrentStageConfig extends StageConfig {
    minLoopIters: number;
    maxLoopIters: number;
    allowBacktracking: boolean;
    allowParallelPaths: boolean;
}
export interface LoopControlConfig {
    maxLoopIters: number;
    minLoopIters: number;
    maxRevisionDepth: number;
}
export interface ConfidenceThresholds {
    earlyExit: number;
    revise: number;
    floor: number;
}
export interface ConfidenceConfig {
    thresholds: ConfidenceThresholds;
    adaptive: boolean;
    adaptUpDelta: number;
    adaptDownDelta: number;
    smoothingFactor: number;
}
export interface MoERoutingConfig {
    enabled: boolean;
    routedExperts: string[];
    sharedExperts: string[];
    topK: number;
    maxParallelExperts: number;
    loadBalanceWindow: number;
}
export interface AttentionConfig {
    defaultMode: AttentionMode;
    switchByTask: boolean;
    modeSwitchComplexityThreshold: number;
    moe: MoERoutingConfig;
}
export interface RDTConfig {
    enabled: boolean;
    profile: ReasoningDepthProfile;
    prelude: StageConfig;
    recurrent: RecurrentStageConfig;
    coda: StageConfig;
    loop: LoopControlConfig;
    confidence: ConfidenceConfig;
    attention: AttentionConfig;
    quality: {
        enableTraceLogging: boolean;
        preserveReasoningChain: boolean;
        computeAdaptive: boolean;
        enableMultiHop: boolean;
    };
}
export interface IterationQualityMetrics {
    coherence: number;
    completeness: number;
    consistency: number;
    aggregate: number;
    explanation: string;
}
export interface RDTIterationState {
    iteration: number;
    summary: string;
    reasoning: string[];
    confidence: number;
    confidenceThreshold: number;
    attentionMode: Exclude<AttentionMode, 'auto'>;
    routedExperts: string[];
    sharedExperts: string[];
    quality: IterationQualityMetrics;
    revisedFromIteration?: number;
    parallelPathId?: string;
}
export interface RDTReasoningState {
    stage: RDTStageName;
    prompt: string;
    decomposition: string[];
    trace: RDTIterationState[];
    bestIteration?: RDTIterationState;
    finalAnswer?: string;
    haltedEarly: boolean;
    metadata: Record<string, unknown>;
}
export type RDTProgressEvent = {
    type: 'rdt_stage_started';
    stage: RDTStageName;
} | {
    type: 'rdt_stage_completed';
    stage: RDTStageName;
    latencyMs: number;
} | {
    type: 'rdt_iteration_completed';
    iteration: number;
    confidence: number;
    threshold: number;
    attentionMode: Exclude<AttentionMode, 'auto'>;
    routedExperts: string[];
    quality: IterationQualityMetrics;
} | {
    type: 'rdt_backtrack';
    iteration: number;
    fromConfidence: number;
    toConfidence: number;
    reason: string;
} | {
    type: 'rdt_parallel_path';
    iteration: number;
    selectedPath: string;
    candidatePaths: string[];
} | {
    type: 'rdt_early_exit';
    iteration: number;
    confidence: number;
    threshold: number;
    reason: string;
} | {
    type: 'rdt_quality';
    iteration: number;
    quality: IterationQualityMetrics;
} | {
    type: 'rdt_trace';
    message: string;
    data?: Record<string, unknown>;
} | {
    type: 'rdt_output_delta';
    stage: RDTStageName;
    text: string;
};
export interface RDTPromptRequest {
    stage: RDTStageName;
    prompt: string;
    temperature: number;
    maxTokens?: number;
    metadata?: Record<string, unknown>;
}
export interface RDTResult {
    finalText: string;
    loopsUsed: number;
    finalConfidence: number;
    haltedEarly: boolean;
    trace: RDTIterationState[];
    quality: {
        avgCoherence: number;
        avgCompleteness: number;
        avgConsistency: number;
        avgAggregate: number;
    };
}
export interface RDTRuntimeInput {
    prompt: string;
    context?: string[];
    tokenBudget?: {
        maxInputChars?: number;
        maxOutputChars?: number;
    };
    metadata?: Record<string, unknown>;
}
export interface RDTRuntimeDeps {
    config: RDTConfig;
    invoke(request: RDTPromptRequest): AsyncGenerator<string, string, void>;
    emit?(event: RDTProgressEvent): Promise<void> | void;
}
export declare const RDT_PROFILES: Record<ReasoningDepthProfile, Partial<RDTConfig>>;
//# sourceMappingURL=rdt.types.d.ts.map