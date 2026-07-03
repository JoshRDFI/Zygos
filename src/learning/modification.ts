import { randomUUID } from 'node:crypto';
import type {
  ABTestRecord,
  LearningProposal,
  LearningRuntimeDeps,
  ToolExecutionObservation,
  ToolModificationProposal,
  ToolPerformanceMetrics
} from '../types/learning.types.js';
import type { ToolDefinition } from '../types/tool.types.js';

interface ModificationOptions {
  minObservationsForProposal: number;
  minSuccessRateGain: number;
  maxLatencyRegressionRatio: number;
  abTestSampleSize: number;
  maxResourceCostPerTestMs: number;
}

export class ToolModificationSystem {
  constructor(
    private readonly runtime: LearningRuntimeDeps,
    private readonly options: ModificationOptions
  ) {}

  analyzeToolPerformance(observations: ToolExecutionObservation[]): ToolPerformanceMetrics[] {
    const byTool = new Map<string, ToolExecutionObservation[]>();
    for (const obs of observations) {
      const arr = byTool.get(obs.toolCall.name) ?? [];
      arr.push(obs);
      byTool.set(obs.toolCall.name, arr);
    }

    const metrics: ToolPerformanceMetrics[] = [];
    for (const [toolName, entries] of byTool) {
      const durations = entries.map((entry) => entry.result.durationMs).sort((a, b) => a - b);
      const successCount = entries.filter((entry) => entry.result.ok).length;
      const errors = new Map<string, number>();
      for (const entry of entries) {
        const key = entry.result.normalizedError?.code ?? (entry.result.error ? 'generic_error' : 'none');
        errors.set(key, (errors.get(key) ?? 0) + (entry.result.ok ? 0 : 1));
      }

      const sampleSize = entries.length;
      const successRate = sampleSize > 0 ? successCount / sampleSize : 0;
      const averageLatencyMs = sampleSize > 0 ? durations.reduce((acc, cur) => acc + cur, 0) / sampleSize : 0;
      const p95LatencyMs = sampleSize > 0 ? durations[Math.min(sampleSize - 1, Math.floor(sampleSize * 0.95))] : 0;
      const errorRate = 1 - successRate;

      metrics.push({
        toolName,
        sampleSize,
        successRate,
        errorRate,
        averageLatencyMs,
        p95LatencyMs,
        frequentErrors: [...errors.entries()]
          .filter(([errorCode, count]) => errorCode !== 'none' && count > 0)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([code, count]) => ({ code, count })),
        regressionDetected: successRate < 0.6 || p95LatencyMs > averageLatencyMs * 2.5
      });
    }

    return metrics.sort((a, b) => a.successRate - b.successRate || b.averageLatencyMs - a.averageLatencyMs);
  }

  createImprovementProposals(metrics: ToolPerformanceMetrics[], observations: ToolExecutionObservation[]): LearningProposal[] {
    const proposals: LearningProposal[] = [];

    for (const metric of metrics) {
      if (metric.sampleSize < this.options.minObservationsForProposal) {
        continue;
      }

      if (!(metric.successRate < 0.85 || metric.p95LatencyMs > 1_500 || metric.regressionDetected)) {
        continue;
      }

      const baseline = this.runtime.getTool(metric.toolName);
      if (!baseline) {
        continue;
      }

      const toolObs = observations.filter((obs) => obs.toolCall.name === metric.toolName).slice(0, 20);
      const patch = {
        timeoutMs: Math.max(baseline.meta.timeoutMs ?? 30_000, Math.round(metric.p95LatencyMs * 1.5) + 100),
        retryAttempts: Math.max(1, Math.min(4, (baseline.meta.retry?.attempts ?? 1) + 1)),
        retryBackoffMs: Math.max(200, baseline.meta.retry?.backoffMs ?? 250),
        maxResultBytes: baseline.meta.maxResultBytes,
        description: `${baseline.meta.description} (optimized based on runtime feedback)`
      };

      const candidate: ToolDefinition = {
        ...baseline,
        meta: {
          ...baseline.meta,
          timeoutMs: patch.timeoutMs,
          description: patch.description,
          retry: {
            attempts: patch.retryAttempts,
            backoffMs: patch.retryBackoffMs
          }
        }
      };

      const payload: ToolModificationProposal = {
        type: 'modification',
        toolName: metric.toolName,
        candidateDefinition: candidate,
        patch,
        expectedDelta: {
          successRateDelta: Math.max(this.options.minSuccessRateGain, 0.02),
          latencyDeltaMs: Math.max(10, Math.round(metric.averageLatencyMs * 0.1)),
          errorRateDelta: 0.02
        },
        testPlan: {
          sampleCalls: toolObs.map((obs) => obs.toolCall),
          minImprovement: this.options.minSuccessRateGain,
          maxRegressionTolerance: this.options.maxLatencyRegressionRatio
        },
        explanation: `Detected tool inefficiency for ${metric.toolName}: success=${metric.successRate.toFixed(2)}, p95=${metric.p95LatencyMs.toFixed(0)}ms.`
      };

      proposals.push({
        id: randomUUID(),
        kind: 'modification',
        status: 'proposed',
        risk: metric.successRate < 0.65 ? 'medium' : 'low',
        source: 'hybrid',
        requestedBy: 'learning_manager',
        payload,
        createdAt: Date.now(),
        updatedAt: Date.now()
      });
    }

    return proposals;
  }

  async runABTest(proposal: ToolModificationProposal): Promise<ABTestRecord> {
    const baseline = this.runtime.getTool(proposal.toolName);
    if (!baseline) {
      throw new Error(`Tool not found for A/B test: ${proposal.toolName}`);
    }

    const calls = proposal.testPlan.sampleCalls.slice(0, this.options.abTestSampleSize);
    if (calls.length === 0 || !this.runtime.executeForLearning) {
      return {
        id: randomUUID(),
        toolName: proposal.toolName,
        baselineVersionId: proposal.baselineVersionId ?? 0,
        candidateVersionId: proposal.baselineVersionId ?? 0,
        sampleSize: 0,
        baselineSuccessRate: 1,
        candidateSuccessRate: 1,
        baselineLatencyMs: 0,
        candidateLatencyMs: 0,
        status: 'aborted',
        createdAt: Date.now(),
        completedAt: Date.now()
      };
    }

    const originalDef = baseline;
    const patchedDef = proposal.candidateDefinition;

    let baselineOk = 0;
    let candidateOk = 0;
    let baselineLatency = 0;
    let candidateLatency = 0;

    for (const call of calls) {
      const baselineResult = await this.runtime.executeForLearning({ ...call, name: originalDef.meta.name });
      baselineLatency += baselineResult.durationMs;
      if (baselineResult.ok) baselineOk += 1;

      // temporarily swap for candidate execution
      this.runtime.updateTool(proposal.toolName, patchedDef);
      const started = Date.now();
      const candidateResult = await this.runtime.executeForLearning({ ...call, name: patchedDef.meta.name });
      const elapsed = Date.now() - started;
      candidateLatency += Math.min(candidateResult.durationMs || elapsed, this.options.maxResourceCostPerTestMs);
      if (candidateResult.ok) candidateOk += 1;
      this.runtime.updateTool(proposal.toolName, originalDef);
    }

    const record: ABTestRecord = {
      id: randomUUID(),
      toolName: proposal.toolName,
      baselineVersionId: proposal.baselineVersionId ?? 0,
      candidateVersionId: (proposal.baselineVersionId ?? 0) + 1,
      sampleSize: calls.length,
      baselineSuccessRate: baselineOk / calls.length,
      candidateSuccessRate: candidateOk / calls.length,
      baselineLatencyMs: baselineLatency / calls.length,
      candidateLatencyMs: candidateLatency / calls.length,
      status: 'completed',
      winnerVersionId:
        candidateOk / calls.length >= baselineOk / calls.length &&
        candidateLatency / calls.length <= baselineLatency / calls.length * (1 + this.options.maxLatencyRegressionRatio)
          ? (proposal.baselineVersionId ?? 0) + 1
          : proposal.baselineVersionId,
      createdAt: Date.now(),
      completedAt: Date.now()
    };

    return record;
  }

  shouldApply(abTest: ABTestRecord): boolean {
    if (abTest.status !== 'completed' || abTest.sampleSize === 0) {
      return false;
    }

    const successGain = abTest.candidateSuccessRate - abTest.baselineSuccessRate;
    const latencyRatio = abTest.baselineLatencyMs === 0 ? 1 : abTest.candidateLatencyMs / abTest.baselineLatencyMs;

    return successGain >= this.options.minSuccessRateGain && latencyRatio <= 1 + this.options.maxLatencyRegressionRatio;
  }
}
