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

const defaultPolicy: PermissionPolicy = {
  defaultDecision: 'allow',
  rules: [
    { pattern: '*', decision: 'require_approval', roles: ['user'] },
    { pattern: '*', decision: 'allow', roles: ['system', 'admin'] }
  ]
};

function matchPattern(name: string, pattern: string): boolean {
  if (pattern === '*') return true;
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`).test(name);
}

export class PermissionManager {
  private readonly logger: StructuredLogger;

  constructor(private readonly policy: PermissionPolicy = defaultPolicy, logger?: StructuredLogger) {
    this.logger = logger ?? new StructuredLogger('tools.permissions', false);
  }

  check(tool: ToolMeta, ctx: ToolExecutionContext): PermissionCheckResult {
    const merged = this.resolvePolicy(this.policy);
    const role = ctx.role ?? 'user';
    const tags = new Set((ctx.conversationState?.tags as string[] | undefined) ?? []);

    if (tool.permission === 'deny' || tool.permissionRequirement === 'deny') {
      return this.deny(tool, ctx, 'tool metadata denies execution');
    }

    if ((ctx.deniedTools ?? []).includes(tool.name)) {
      return this.deny(tool, ctx, 'tool denied in execution context');
    }

    const matched = merged.rules.find((rule) => {
      if (!matchPattern(tool.name, rule.pattern)) return false;
      if (rule.roles && !rule.roles.includes(role)) return false;
      if (rule.requireConversationTag && !tags.has(rule.requireConversationTag)) return false;
      return true;
    });

    const decision = this.applyOverrides(matched?.decision ?? merged.defaultDecision, tool, ctx);

    if (decision === 'deny') {
      return this.deny(tool, ctx, 'permission rule denied');
    }

    if (decision === 'require_approval') {
      const approved = (ctx.approvedTools ?? []).includes(tool.name);
      if (!approved) {
        return this.deny(tool, ctx, 'approval required but not granted', 'require_approval');
      }
    }

    return {
      allowed: true,
      decision,
      requiresApproval: decision === 'require_approval'
    };
  }

  private applyOverrides(base: PermissionDecision, tool: ToolMeta, ctx: ToolExecutionContext): PermissionDecision {
    if (tool.permissionRequirement === 'deny') return 'deny';
    if (tool.permissionRequirement === 'require_approval') return 'require_approval';

    if (tool.destructive && (ctx.role ?? 'user') !== 'admin') {
      return 'require_approval';
    }

    return base;
  }

  private resolvePolicy(policy: PermissionPolicy): PermissionPolicy {
    if (!policy.inherit) return policy;
    const base = this.resolvePolicy(policy.inherit);
    return {
      defaultDecision: policy.defaultDecision ?? base.defaultDecision,
      rules: [...base.rules, ...policy.rules]
    };
  }

  private deny(
    tool: ToolMeta,
    ctx: ToolExecutionContext,
    reason: string,
    decision: PermissionDecision = 'deny'
  ): PermissionCheckResult {
    this.logger.log('warn', 'Tool permission denied', {
      tool: tool.name,
      sessionId: ctx.sessionId,
      turnId: ctx.turnId,
      role: ctx.role ?? 'user',
      reason
    });

    return {
      allowed: false,
      decision,
      reason,
      requiresApproval: decision === 'require_approval'
    };
  }
}
