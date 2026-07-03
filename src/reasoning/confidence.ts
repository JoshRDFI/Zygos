import type { ConfidenceConfig, IterationQualityMetrics, RDTIterationState } from '../types/rdt.types.js';

function clamp(value: number, min = 0, max = 1): number {
  return Math.max(min, Math.min(max, value));
}

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((token) => token.length > 2);
}

function overlapScore(a: string[], b: string[]): number {
  if (a.length === 0 || b.length === 0) return 0.35;
  const aSet = new Set(a);
  const bSet = new Set(b);
  const intersection = [...aSet].filter((token) => bSet.has(token)).length;
  const union = new Set([...aSet, ...bSet]).size;
  return union === 0 ? 0 : intersection / union;
}

function containsConclusion(summary: string): boolean {
  const markers = ['therefore', 'final', 'answer', 'conclusion', 'thus', 'result'];
  const lower = summary.toLowerCase();
  return markers.some((marker) => lower.includes(marker));
}

function contradictionHint(summary: string): number {
  const lower = summary.toLowerCase();
  const weakSignals = ['maybe', 'unsure', 'not certain', 'unclear'];
  const conflictSignals = ['however', 'but', 'on the other hand', 'contradict'];
  const weakPenalty = weakSignals.some((signal) => lower.includes(signal)) ? 0.12 : 0;
  const conflictPenalty = conflictSignals.some((signal) => lower.includes(signal)) ? 0.08 : 0;
  return clamp(1 - (weakPenalty + conflictPenalty));
}

export interface ConfidenceAssessment {
  confidence: number;
  threshold: number;
  shouldExit: boolean;
  shouldRevise: boolean;
  metrics: IterationQualityMetrics;
}

export class ConfidenceEvaluator {
  private adaptiveThreshold: number;
  private readonly history: Array<{ confidence: number; threshold: number; metrics: IterationQualityMetrics }> = [];

  constructor(private readonly config: ConfidenceConfig) {
    this.adaptiveThreshold = clamp(config.thresholds.earlyExit);
  }

  evaluate(current: string, prior: RDTIterationState | undefined, decomposition: string[]): ConfidenceAssessment {
    const priorSummary = prior?.summary ?? '';
    const currentTokens = tokenize(current);
    const priorTokens = tokenize(priorSummary);

    const coherence = clamp(0.45 + overlapScore(currentTokens, priorTokens) * 0.55);
    const decompositionCoverage = decomposition.length === 0
      ? 1
      : decomposition.filter((step) => current.toLowerCase().includes(step.toLowerCase().slice(0, 24))).length / decomposition.length;
    const sizeAdequacy = clamp(Math.min(1, current.length / 220));
    const completeness = clamp(sizeAdequacy * 0.5 + decompositionCoverage * 0.35 + (containsConclusion(current) ? 0.15 : 0));
    const consistency = contradictionHint(current);

    const aggregate = clamp(coherence * 0.4 + completeness * 0.35 + consistency * 0.25);
    const confidence = this.smoothConfidence(aggregate, prior?.confidence);

    if (this.config.adaptive) {
      this.adaptThreshold(confidence, prior?.confidence ?? confidence);
    }

    const threshold = this.adaptiveThreshold;
    const metrics: IterationQualityMetrics = {
      coherence,
      completeness,
      consistency,
      aggregate,
      explanation: `coherence=${coherence.toFixed(2)}, completeness=${completeness.toFixed(2)}, consistency=${consistency.toFixed(2)}`
    };

    const shouldExit = confidence >= threshold;
    const shouldRevise = confidence < this.config.thresholds.revise;

    this.history.push({ confidence, threshold, metrics });

    return {
      confidence,
      threshold,
      shouldExit,
      shouldRevise,
      metrics
    };
  }

  getHistory(): Array<{ confidence: number; threshold: number; metrics: IterationQualityMetrics }> {
    return [...this.history];
  }

  getAdaptiveThreshold(): number {
    return this.adaptiveThreshold;
  }

  private smoothConfidence(raw: number, prior?: number): number {
    if (prior === undefined) return clamp(raw);
    return clamp(prior * this.config.smoothingFactor + raw * (1 - this.config.smoothingFactor));
  }

  private adaptThreshold(current: number, previous: number): void {
    if (current > previous + 0.08) {
      this.adaptiveThreshold = clamp(this.adaptiveThreshold + this.config.adaptUpDelta, this.config.thresholds.floor, 0.98);
      return;
    }

    if (current < previous - 0.08) {
      this.adaptiveThreshold = clamp(this.adaptiveThreshold - this.config.adaptDownDelta, this.config.thresholds.floor, 0.98);
    }
  }
}
