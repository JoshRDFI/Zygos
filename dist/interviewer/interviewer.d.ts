import type { BuildPlan, BuildPlanExport, InterviewConfig, InterviewManagerLike, InterviewMetrics, InterviewResponse, InterviewSession, InterviewStartInput, InterviewTemplate, ProjectType } from '../types/interviewer.types.js';
export interface InterviewerDeps {
    dbPath: string;
    config: InterviewConfig;
    askProvider?: (prompt: string) => Promise<string>;
}
export declare class Interviewer implements InterviewManagerLike {
    private readonly deps;
    private db;
    private readonly planGenerator;
    constructor(deps: InterviewerDeps);
    init(): Promise<void>;
    start(input: InterviewStartInput): Promise<InterviewResponse>;
    answer(sessionId: string, answer: string, stakeholderId?: string): Promise<InterviewResponse>;
    complete(sessionId: string): Promise<BuildPlan | null>;
    getSession(sessionId: string): Promise<InterviewSession | null>;
    getPlan(sessionId: string): Promise<BuildPlan | null>;
    exportPlan(sessionId: string): Promise<BuildPlanExport | null>;
    shouldGateBuild(userMessage: string): Promise<{
        gated: boolean;
        reason?: string;
    }>;
    getMetrics(): InterviewMetrics;
    private nextFromSession;
    private generateNextQuestion;
    private adaptiveFollowUp;
    private needsClarification;
    private shouldComplete;
    private updateSignals;
    private answerConfidence;
    private inferProjectType;
    private getTemplate;
    private estimateMessageComplexity;
    private safeProviderQuestion;
    private persistSession;
    private persistTurn;
    private persistPlan;
    private assertDb;
}
export declare const INTERVIEW_TEMPLATES: Record<ProjectType, InterviewTemplate>;
//# sourceMappingURL=interviewer.d.ts.map