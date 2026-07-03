import { z } from 'zod';
import type { ContextSnapshot } from './context.types.js';
import type { ToolCall, ToolDefinition, ToolResult } from './tool.types.js';
export declare const learningProposalKindSchema: z.ZodEnum<["modification", "creation"]>;
export type LearningProposalKind = z.infer<typeof learningProposalKindSchema>;
export declare const learningProposalStatusSchema: z.ZodEnum<["proposed", "approved", "rejected", "applied", "rolled_back"]>;
export type LearningProposalStatus = z.infer<typeof learningProposalStatusSchema>;
export declare const learningRiskSchema: z.ZodEnum<["low", "medium", "high"]>;
export type LearningRisk = z.infer<typeof learningRiskSchema>;
export declare const learningApprovalModeSchema: z.ZodEnum<["auto", "manual", "optional_human"]>;
export type LearningApprovalMode = z.infer<typeof learningApprovalModeSchema>;
export interface ToolPerformanceMetrics {
    toolName: string;
    sampleSize: number;
    successRate: number;
    errorRate: number;
    averageLatencyMs: number;
    p95LatencyMs: number;
    frequentErrors: Array<{
        code: string;
        count: number;
    }>;
    regressionDetected: boolean;
}
export interface ToolExecutionObservation {
    id?: number;
    sessionId: string;
    turnId: string;
    toolCall: ToolCall;
    result: ToolResult;
    contextTags?: string[];
    contextSnapshot?: Pick<ContextSnapshot, 'sessionId' | 'window' | 'createdAt'>;
    createdAt: number;
}
export interface LearningImprovementDelta {
    successRateDelta: number;
    latencyDeltaMs: number;
    errorRateDelta: number;
}
export interface ToolModificationPatch {
    timeoutMs?: number;
    retryAttempts?: number;
    retryBackoffMs?: number;
    promptPrefix?: string;
    description?: string;
    maxResultBytes?: number;
    warnings?: string[];
}
export interface ToolModificationProposal {
    type: 'modification';
    toolName: string;
    baselineVersionId?: number;
    candidateDefinition: ToolDefinition;
    patch: ToolModificationPatch;
    expectedDelta: LearningImprovementDelta;
    testPlan: {
        sampleCalls: ToolCall[];
        minImprovement: number;
        maxRegressionTolerance: number;
    };
    explanation: string;
}
export interface ToolCreationSpec {
    name: string;
    description: string;
    template: 'json_transform' | 'text_template' | 'math_expression';
    requiredKeys: string[];
    parameterHints: Record<string, string>;
}
export interface ToolCreationProposal {
    type: 'creation';
    spec: ToolCreationSpec;
    generatedDefinition: ToolDefinition;
    validationReport: {
        passed: boolean;
        warnings: string[];
        blockedReasons: string[];
    };
    explanation: string;
}
export type LearningProposalPayload = ToolModificationProposal | ToolCreationProposal;
export interface LearningProposal {
    id: string;
    kind: LearningProposalKind;
    status: LearningProposalStatus;
    risk: LearningRisk;
    createdAt: number;
    updatedAt: number;
    source: 'heuristic' | 'llm' | 'hybrid';
    requestedBy: string;
    approvedBy?: string;
    payload: LearningProposalPayload;
}
export interface ABTestRecord {
    id: string;
    toolName: string;
    baselineVersionId: number;
    candidateVersionId: number;
    sampleSize: number;
    baselineSuccessRate: number;
    candidateSuccessRate: number;
    baselineLatencyMs: number;
    candidateLatencyMs: number;
    winnerVersionId?: number;
    status: 'running' | 'completed' | 'aborted';
    createdAt: number;
    completedAt?: number;
}
export interface ToolVersionRecord {
    id: number;
    toolName: string;
    version: string;
    branch: string;
    reason: string;
    actor: string;
    changeType: 'register' | 'modify' | 'create' | 'rollback' | 'merge';
    definition: ToolDefinition;
    metrics?: Partial<ToolPerformanceMetrics>;
    parentVersionId?: number;
    isStable: boolean;
    tags: string[];
    createdAt: number;
}
export interface LearningAuditEntry {
    id?: number;
    action: 'observe' | 'proposal_created' | 'proposal_approved' | 'proposal_rejected' | 'proposal_applied' | 'ab_test_completed' | 'rollback' | 'safety_blocked';
    entityType: 'tool' | 'proposal' | 'version' | 'learning';
    entityId: string;
    details: Record<string, unknown>;
    createdAt: number;
}
export interface LearningRecommendation {
    toolName?: string;
    summary: string;
    priority: 'low' | 'medium' | 'high';
    proposalId?: string;
}
export interface LearningManagerMetrics {
    observedExecutions: number;
    proposalsCreated: number;
    proposalsApplied: number;
    proposalsRejected: number;
    rollbacks: number;
    averageSuccessRateGain: number;
    averageLatencyGainMs: number;
}
export interface LearningState {
    enabled: boolean;
    approvalMode: LearningApprovalMode;
    lastCycleAt?: number;
    metrics: LearningManagerMetrics;
    recommendations: LearningRecommendation[];
}
export interface LearningConfig {
    enabled: boolean;
    approvalMode: LearningApprovalMode;
    autoApplyLowRisk: boolean;
    maxProposalsPerCycle: number;
    minObservationsForProposal: number;
    observeWindowSize: number;
    maxModificationsPerHour: number;
    maxToolCreationsPerDay: number;
    abTestSampleSize: number;
    maxLatencyRegressionRatio: number;
    minSuccessRateGain: number;
    maxResourceCostPerTestMs: number;
}
export interface LearningRuntimeDeps {
    listTools(): ToolDefinition[];
    getTool(name: string): ToolDefinition | undefined;
    registerTool(definition: ToolDefinition): void;
    updateTool(name: string, definition: ToolDefinition): void;
    removeTool?(name: string): void;
    executeForLearning?(call: ToolCall): Promise<ToolResult>;
}
export interface LearningPersistence {
    init(): Promise<void>;
    close(): Promise<void>;
    recordObservation(observation: ToolExecutionObservation): Promise<void>;
    getRecentObservations(limit: number): Promise<ToolExecutionObservation[]>;
    saveProposal(proposal: LearningProposal): Promise<void>;
    listProposals(status?: LearningProposalStatus): Promise<LearningProposal[]>;
    updateProposalStatus(id: string, status: LearningProposalStatus, approvedBy?: string): Promise<void>;
    saveVersion(record: Omit<ToolVersionRecord, 'id'>): Promise<ToolVersionRecord>;
    listVersions(toolName: string, branch?: string): Promise<ToolVersionRecord[]>;
    saveABTest(record: ABTestRecord): Promise<void>;
    appendAudit(entry: LearningAuditEntry): Promise<void>;
    readState(): Promise<LearningState>;
    writeState(state: LearningState): Promise<void>;
}
//# sourceMappingURL=learning.types.d.ts.map