import type { LearningProposal, LearningRuntimeDeps, ToolCreationProposal, ToolCreationSpec, ToolExecutionObservation } from '../types/learning.types.js';
import type { ToolDefinition } from '../types/tool.types.js';
interface CreationOptions {
    minPatternFrequency: number;
    maxToolCreationsPerDay: number;
}
export declare class ToolCreationEngine {
    private readonly runtime;
    private readonly options;
    constructor(runtime: LearningRuntimeDeps, options: CreationOptions);
    detectOpportunities(observations: ToolExecutionObservation[]): ToolCreationSpec[];
    buildProposal(spec: ToolCreationSpec): LearningProposal;
    applyProposal(proposal: ToolCreationProposal): void;
    validateGeneratedTool(definition: ToolDefinition, spec: ToolCreationSpec): {
        passed: boolean;
        warnings: string[];
        blockedReasons: string[];
    };
    private generateTool;
}
export {};
//# sourceMappingURL=creation.d.ts.map