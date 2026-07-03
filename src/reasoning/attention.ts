import type { AttentionConfig, AttentionMode, RDTIterationState } from '../types/rdt.types.js';

function clamp(value: number, min = 0, max = 1): number {
  return Math.max(min, Math.min(max, value));
}

function splitKeywords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((token) => token.length > 2);
}

export interface AttentionDecision {
  mode: Exclude<AttentionMode, 'auto'>;
  routedExperts: string[];
  sharedExperts: string[];
  computeFraction: number;
  rationale: string;
}

export class AttentionMoEManager {
  private readonly expertLoads = new Map<string, number>();

  constructor(private readonly config: AttentionConfig) {}

  decide(input: {
    prompt: string;
    iteration: number;
    previous?: RDTIterationState;
    decomposition: string[];
  }): AttentionDecision {
    const mode = this.pickMode(input);
    const routedExperts = this.pickRoutedExperts(input.prompt, input.decomposition, input.iteration);
    const sharedExperts = this.pickSharedExperts(routedExperts, input.iteration);
    const computeFraction = this.computeAllocation(input.prompt, input.decomposition, input.previous?.confidence ?? 0.5, input.iteration);

    for (const expert of [...routedExperts, ...sharedExperts]) {
      this.expertLoads.set(expert, (this.expertLoads.get(expert) ?? 0) + 1);
    }

    return {
      mode,
      routedExperts,
      sharedExperts,
      computeFraction,
      rationale: `mode=${mode}, routed=${routedExperts.join('|') || 'none'}, shared=${sharedExperts.join('|') || 'none'}, compute=${computeFraction.toFixed(2)}`
    };
  }

  snapshotLoads(): Record<string, number> {
    return Object.fromEntries(this.expertLoads.entries());
  }

  private pickMode(input: { prompt: string; decomposition: string[]; iteration: number; previous?: RDTIterationState }): 'mla' | 'gqa' {
    if (this.config.defaultMode !== 'auto') return this.config.defaultMode;

    const complexity = this.taskComplexity(input.prompt, input.decomposition);
    if (!this.config.switchByTask) {
      return input.iteration % 2 === 0 ? 'mla' : 'gqa';
    }

    if (complexity >= this.config.modeSwitchComplexityThreshold || (input.previous?.confidence ?? 0) < 0.6) {
      return 'mla';
    }
    return 'gqa';
  }

  private pickRoutedExperts(prompt: string, decomposition: string[], iteration: number): string[] {
    if (!this.config.moe.enabled) return [];

    const haystack = splitKeywords(`${prompt} ${decomposition.join(' ')}`);
    const scored = this.config.moe.routedExperts.map((expert) => {
      const key = expert.toLowerCase();
      const keywordScore = haystack.some((token) => key.includes(token) || token.includes(key)) ? 1 : 0;
      const load = this.expertLoads.get(expert) ?? 0;
      const loadPenalty = Math.min(0.3, load / Math.max(1, this.config.moe.loadBalanceWindow * 2));
      const explorationBoost = iteration % 3 === 0 ? 0.1 : 0;
      return { expert, score: keywordScore + explorationBoost - loadPenalty };
    });

    const topK = Math.min(this.config.moe.topK, this.config.moe.maxParallelExperts, scored.length);
    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, topK)
      .map((entry) => entry.expert);
  }

  private pickSharedExperts(routedExperts: string[], iteration: number): string[] {
    if (!this.config.moe.enabled) return [];

    const slots = Math.max(1, this.config.moe.maxParallelExperts - routedExperts.length);
    const sorted = [...this.config.moe.sharedExperts].sort((a, b) => {
      const aLoad = this.expertLoads.get(a) ?? 0;
      const bLoad = this.expertLoads.get(b) ?? 0;
      return aLoad - bLoad;
    });

    const sampled = sorted.slice(0, slots);
    if (iteration % 2 === 1 && sorted.length > sampled.length) {
      sampled.push(sorted[sampled.length]);
    }

    return [...new Set(sampled)].slice(0, slots);
  }

  private computeAllocation(prompt: string, decomposition: string[], confidence: number, iteration: number): number {
    const complexity = this.taskComplexity(prompt, decomposition);
    const lowConfidenceBoost = clamp((0.75 - confidence) * 0.8, 0, 0.4);
    const recurrentBoost = Math.min(0.2, iteration * 0.04);
    return clamp(0.35 + complexity * 0.35 + lowConfidenceBoost + recurrentBoost, 0.25, 1);
  }

  private taskComplexity(prompt: string, decomposition: string[]): number {
    const keywords = splitKeywords(prompt);
    const multiHopMarkers = ['why', 'because', 'compare', 'tradeoff', 'analyze', 'multi', 'step'];
    const markerScore = multiHopMarkers.filter((marker) => keywords.includes(marker)).length / multiHopMarkers.length;
    const decompositionScore = Math.min(1, decomposition.length / 6);
    const lengthScore = Math.min(1, prompt.length / 500);
    return clamp(markerScore * 0.4 + decompositionScore * 0.35 + lengthScore * 0.25);
  }
}
