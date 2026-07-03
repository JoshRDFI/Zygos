import { StructuredLogger } from '../providers/observability.js';
import type { PermissionDecision, ToolExecutionContext, ToolMeta } from '../types/tool.types.js';
export type ToolRole = 'user' | 'system' | 'admin';
export interface PermissionRule {
    pattern: string;
    decision: PermissionDecision;
    roles?: ToolRole[];
    requireConversationTag?: string;
}
export interface PermissionPolicy {
    defaultDecision: PermissionDecision;
    rules: PermissionRule[];
    inherit?: PermissionPolicy;
}
export interface PermissionCheckResult {
    allowed: boolean;
    decision: PermissionDecision;
    reason?: string;
    requiresApproval: boolean;
}
export declare class PermissionManager {
    private readonly policy;
    private readonly logger;
    constructor(policy?: PermissionPolicy, logger?: StructuredLogger);
    check(tool: ToolMeta, ctx: ToolExecutionContext): PermissionCheckResult;
    private applyOverrides;
    private resolvePolicy;
    private deny;
}
//# sourceMappingURL=permissions.d.ts.map