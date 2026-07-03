import type { BuildPlan, BuildPlanExport, InterviewSession } from '../types/interviewer.types.js';
export declare class BuildPlanGenerator {
    generate(session: InterviewSession): BuildPlan;
    export(plan: BuildPlan): BuildPlanExport;
    private extractRequirements;
    private extractConstraints;
    private extractRisks;
    private extractAssumptions;
    private extractUnresolvedQuestions;
    private buildSummary;
    private recommendationsFor;
    private buildRoadmap;
    private requirementTasks;
    private inferAcceptanceCriteria;
}
//# sourceMappingURL=plan-generator.d.ts.map