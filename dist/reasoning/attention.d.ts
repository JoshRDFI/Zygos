import type { AttentionConfig, AttentionMode, RDTIterationState } from '../types/rdt.types.js';
export interface AttentionDecision {
    mode: Exclude<AttentionMode, 'auto'>;
    routedExperts: string[];
    sharedExperts: string[];
    computeFraction: number;
    rationale: string;
}
export declare class AttentionMoEManager {
    private readonly config;
    private readonly expertLoads;
    constructor(config: AttentionConfig);
    decide(input: {
        prompt: string;
        iteration: number;
        previous?: RDTIterationState;
        decomposition: string[];
    }): AttentionDecision;
    snapshotLoads(): Record<string, number>;
    private pickMode;
    private pickRoutedExperts;
    private pickSharedExperts;
    private computeAllocation;
    private taskComplexity;
}
//# sourceMappingURL=attention.d.ts.map