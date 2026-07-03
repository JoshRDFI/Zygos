import type { ConfidenceConfig, IterationQualityMetrics, RDTIterationState } from '../types/rdt.types.js';
export interface ConfidenceAssessment {
    confidence: number;
    threshold: number;
    shouldExit: boolean;
    shouldRevise: boolean;
    metrics: IterationQualityMetrics;
}
export declare class ConfidenceEvaluator {
    private readonly config;
    private adaptiveThreshold;
    private readonly history;
    constructor(config: ConfidenceConfig);
    evaluate(current: string, prior: RDTIterationState | undefined, decomposition: string[]): ConfidenceAssessment;
    getHistory(): Array<{
        confidence: number;
        threshold: number;
        metrics: IterationQualityMetrics;
    }>;
    getAdaptiveThreshold(): number;
    private smoothConfidence;
    private adaptThreshold;
}
//# sourceMappingURL=confidence.d.ts.map