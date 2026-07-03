import type { RDTResult, RDTRuntimeDeps, RDTRuntimeInput } from '../types/rdt.types.js';
export declare class RDTRuntime {
    private readonly deps;
    private readonly attentionManager;
    private readonly confidenceEvaluator;
    constructor(deps: RDTRuntimeDeps);
    run(input: RDTRuntimeInput): Promise<RDTResult>;
    private runRecurrentIteration;
    private shouldRunParallelPaths;
    private buildPreludePrompt;
    private buildRecurrentPrompt;
    private buildCodaPrompt;
    private parsePayload;
    private invokeStage;
    private aggregateQuality;
    private emit;
}
//# sourceMappingURL=rdt-runtime.d.ts.map