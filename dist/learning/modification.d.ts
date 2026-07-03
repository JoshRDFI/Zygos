import type { ABTestRecord, LearningProposal, LearningRuntimeDeps, ToolExecutionObservation, ToolModificationProposal, ToolPerformanceMetrics } from '../types/learning.types.js';
interface ModificationOptions {
    minObservationsForProposal: number;
    minSuccessRateGain: number;
    maxLatencyRegressionRatio: number;
    abTestSampleSize: number;
    maxResourceCostPerTestMs: number;
}
export declare class ToolModificationSystem {
    private readonly runtime;
    private readonly options;
    constructor(runtime: LearningRuntimeDeps, options: ModificationOptions);
    analyzeToolPerformance(observations: ToolExecutionObservation[]): ToolPerformanceMetrics[];
    createImprovementProposals(metrics: ToolPerformanceMetrics[], observations: ToolExecutionObservation[]): LearningProposal[];
    runABTest(proposal: ToolModificationProposal): Promise<ABTestRecord>;
    shouldApply(abTest: ABTestRecord): boolean;
}
export {};
//# sourceMappingURL=modification.d.ts.map