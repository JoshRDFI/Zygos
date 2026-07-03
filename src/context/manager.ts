import { randomUUID } from 'node:crypto';
import { writeFile, readFile } from 'node:fs/promises';
import type {
  ContextManagerLike,
  ContextPostTurnInput,
  ContextPreparationResult,
  ContextSnapshot,
  ContextTurn,
  CompactionStrategy,
  MemoryFact,
  SearchQuery,
  SearchResult,
  TokenBudgetPlan,
  TokenBudgetReport
} from '../types/context.types.js';
import type { UserTurnInput } from '../types/core.types.js';
import { ContextCompactor, HeuristicSummaryGenerator } from './compaction.js';
import { ContextSearch } from './search.js';
import { SQLiteContextStorage } from './storage.js';
import { TokenBudgetSystem } from './budget.js';
import { ContextMetrics, StructuredLogger } from '../providers/observability.js';

export interface ContextManagerOptions {
  defaultModelContextTokens?: number;
  compactionStrategy?: CompactionStrategy;
  maxCachedSnapshots?: number;
  snapshotTtlMs?: number;
}

interface CacheEntry {
  snapshot: ContextSnapshot;
  expiresAt: number;
}

const DEFAULT_COMPACTION_STRATEGY: CompactionStrategy = {
  type: 'hierarchical',
  targetReductionRatio: 0.72,
  preserveToolPairs: true,
  preserveTaggedTurns: true,
  preserveRecentTurns: 10,
  maxSummaryTokens: 300
};

export class ContextManager implements ContextManagerLike {
  private readonly budget = new TokenBudgetSystem();
  private readonly compactor: ContextCompactor;
  private readonly searchService: ContextSearch;
  private readonly snapshotCache = new Map<string, CacheEntry>();
  private readonly logger = new StructuredLogger('context.manager', process.env.ZYGOS_DEBUG === '1');
  private readonly metrics = new ContextMetrics();
  private readonly lockChains = new Map<string, Promise<void>>();
  private initialized = false;

  constructor(
    private readonly storage: SQLiteContextStorage,
    private readonly options: ContextManagerOptions = {}
  ) {
    this.compactor = new ContextCompactor(this.budget, new HeuristicSummaryGenerator());
    this.searchService = new ContextSearch(storage, { defaultLimit: 8 });
  }

  async init(): Promise<void> {
    if (this.initialized) {
      return;
    }
    await this.storage.init();
    this.initialized = true;
  }

  async prepare(input: UserTurnInput, model = 'default'): Promise<ContextPreparationResult> {
    await this.init();
    const startedAt = Date.now();
    return this.withSessionLock(input.sessionId, async () => {
      const turns = await this.storage.getRecentTurns(input.sessionId, 80, false);
      const sortedTurns = [...turns].sort((a, b) => a.turnIndex - b.turnIndex);
      const modelLimit = this.options.defaultModelContextTokens ?? 32_000;
      const budgetPlan = this.budget.plan({
        maxContextTokens: modelLimit,
        strategy: 'priority_based'
      });

      const searchStarted = Date.now();
      const retrieval = await this.searchService.retrieveMemory(input.sessionId, quoteForFts(input.userMessage), 6);
      this.metrics.recordSearch(Date.now() - searchStarted);
      const selected = this.selectTurns(sortedTurns, retrieval.results, budgetPlan);

      const usedTokens = this.budget.estimateTurns(selected);
      const threshold = Math.round(modelLimit * 0.82);
      let compacted = false;
      const warnings: string[] = [];

      if (usedTokens > threshold) {
        const compaction = await this.compactor.compact({
          sessionId: input.sessionId,
          turns: selected,
          maxTokens: budgetPlan.availableForHistoryTokens,
          strategy: this.options.compactionStrategy ?? DEFAULT_COMPACTION_STRATEGY
        });

        if (compaction.compacted && compaction.summaryTurn) {
          compacted = true;
          this.metrics.recordCompaction();
          await this.storage.markTurnsCompacted(input.sessionId, compaction.removedTurnIds);
          await this.storage.saveTurn(compaction.summaryTurn);
        }
        if (compaction.warning) {
          warnings.push(compaction.warning);
        }
      }

      const freshTurns = await this.storage.getRecentTurns(input.sessionId, 60, false);
      const selectedTurns = this.selectTurns(
        [...freshTurns].sort((a, b) => a.turnIndex - b.turnIndex),
        retrieval.results,
        budgetPlan
      );
      const window = this.budget.buildWindow(model, budgetPlan, this.budget.estimateTurns(selectedTurns));
      const budgetReport = this.budget.createReport(input.sessionId, selectedTurns, window);

      this.primeCache(input.sessionId, {
        sessionId: input.sessionId,
        turns: selectedTurns,
        memory: retrieval.facts,
        window,
        budget: budgetReport,
        createdAt: Date.now()
      });

      this.metrics.recordPrepare(Date.now() - startedAt);
      this.logger.log('debug', 'Prepared context snapshot', {
        sessionId: input.sessionId,
        selectedTurnCount: selectedTurns.length,
        compacted,
        metrics: this.metrics.snapshot()
      });

      return {
        input,
        selectedTurns,
        memory: retrieval,
        window,
        budgetPlan,
        budgetReport,
        compacted,
        warnings
      };
    });
  }

  async postTurnUpdate(input: ContextPostTurnInput): Promise<void> {
    await this.init();
    await this.withSessionLock(input.sessionId, async () => {
      const currentCount = await this.storage.getSessionTurnCount(input.sessionId);
      const now = Date.now();
      const turns: ContextTurn[] = [];
      const route = input.providerRoute;

      turns.push(
        buildTurn({
          sessionId: input.sessionId,
          turnId: input.turnId,
          turnIndex: currentCount + turns.length,
          speaker: 'user',
          contentType: 'message',
          content: input.inputMessage,
          model: route?.model,
          provider: route?.provider,
          createdAt: input.startedAt,
          updatedAt: now,
          tags: autoTags(input.inputMessage),
          importanceScore: scoreImportance(input.inputMessage, 'user')
        })
      );

      for (const toolMsg of input.toolMessages ?? []) {
        turns.push(
          buildTurn({
            sessionId: input.sessionId,
            turnId: input.turnId,
            turnIndex: currentCount + turns.length,
            speaker: 'tool',
            contentType: 'tool_result',
            content: toolMsg,
            model: route?.model,
            provider: route?.provider,
            createdAt: now,
            updatedAt: now,
            tags: ['tool', ...autoTags(toolMsg)],
            importanceScore: scoreImportance(toolMsg, 'tool'),
            toolName: extractToolName(toolMsg)
          })
        );
      }

      turns.push(
        buildTurn({
          sessionId: input.sessionId,
          turnId: input.turnId,
          turnIndex: currentCount + turns.length,
          speaker: 'assistant',
          contentType: 'message',
          content: input.assistantMessage,
          model: route?.model,
          provider: route?.provider,
          createdAt: input.completedAt,
          updatedAt: input.completedAt,
          tags: autoTags(input.assistantMessage),
          importanceScore: scoreImportance(input.assistantMessage, 'assistant')
        })
      );

      await this.storage.upsertSession(input.sessionId);
      await this.storage.saveTurns(turns);

      const facts = extractFacts(input.sessionId, turns);
      if (facts.length > 0) {
        await this.storage.saveFacts(facts);
      }

      for (const turn of turns) {
        this.budget.trackTurn(input.sessionId, turn.tokenUsage ?? estimateUsage(turn.content));
      }

      this.snapshotCache.delete(input.sessionId);
    });
  }

  async getSnapshot(sessionId: string, model = 'default'): Promise<ContextSnapshot | null> {
    await this.init();
    const cached = this.snapshotCache.get(sessionId);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.snapshot;
    }

    const turns = await this.storage.getRecentTurns(sessionId, 60, false);
    if (turns.length === 0) {
      return null;
    }

    const budgetPlan = this.budget.plan({ maxContextTokens: this.options.defaultModelContextTokens ?? 32_000 });
    const window = this.budget.buildWindow(model, budgetPlan, this.budget.estimateTurns(turns));
    const report = this.budget.createReport(sessionId, turns, window);
    const memory = await this.storage.getFacts(sessionId, 20);

    const snapshot: ContextSnapshot = {
      sessionId,
      turns: [...turns].sort((a, b) => a.turnIndex - b.turnIndex),
      memory,
      window,
      budget: report,
      createdAt: Date.now()
    };
    this.primeCache(sessionId, snapshot);
    return snapshot;
  }

  async search(query: SearchQuery): Promise<SearchResult[]> {
    await this.init();
    return this.searchService.query(query);
  }

  async exportSession(sessionId: string, targetPath: string): Promise<void> {
    const snapshot = await this.getSnapshot(sessionId);
    if (!snapshot) {
      throw new Error(`No session found for ${sessionId}`);
    }
    await writeFile(targetPath, JSON.stringify(snapshot, null, 2), 'utf-8');
  }

  async importSession(sourcePath: string): Promise<void> {
    const raw = await readFile(sourcePath, 'utf-8');
    const parsed = JSON.parse(raw) as ContextSnapshot;

    await this.storage.upsertSession(parsed.sessionId);
    await this.storage.saveTurns(parsed.turns);
    await this.storage.saveFacts(parsed.memory);
    this.snapshotCache.delete(parsed.sessionId);
  }

  async backupDatabase(targetPath: string): Promise<void> {
    await this.storage.backupTo(targetPath);
  }

  async restoreDatabase(sourcePath: string): Promise<void> {
    await this.storage.restoreFrom(sourcePath);
    this.snapshotCache.clear();
  }

  getMetrics() {
    return this.metrics.snapshot();
  }

  private selectTurns(turns: ContextTurn[], retrieved: SearchResult[], plan: TokenBudgetPlan): ContextTurn[] {
    const selected: ContextTurn[] = [];
    const selectedIds = new Set<string>();
    let total = 0;

    const appendTurn = (turn: ContextTurn): void => {
      if (selectedIds.has(turn.id)) {
        return;
      }
      const turnTokens = this.budget.estimateTurnTokens(turn);
      if (total + turnTokens > plan.availableForHistoryTokens) {
        return;
      }
      selected.push(turn);
      selectedIds.add(turn.id);
      total += turnTokens;
    };

    for (const turn of turns.slice(-30)) {
      appendTurn(turn);
    }

    for (const hit of retrieved) {
      appendTurn(hit.turn);
    }

    return selected.sort((a, b) => a.turnIndex - b.turnIndex);
  }

  private primeCache(sessionId: string, snapshot: ContextSnapshot): void {
    const maxSize = this.options.maxCachedSnapshots ?? 100;
    const ttl = this.options.snapshotTtlMs ?? 60_000;

    this.snapshotCache.set(sessionId, {
      snapshot,
      expiresAt: Date.now() + ttl
    });

    if (this.snapshotCache.size <= maxSize) {
      return;
    }

    const oldestKey = this.snapshotCache.keys().next().value;
    if (oldestKey) {
      this.snapshotCache.delete(oldestKey);
    }
  }

  private async withSessionLock<T>(sessionId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.lockChains.get(sessionId) ?? Promise.resolve();
    let release: () => void = () => {};
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.lockChains.set(sessionId, previous.then(() => current));

    await previous;
    try {
      return await operation();
    } finally {
      release();
      const latest = this.lockChains.get(sessionId);
      if (latest === current) {
        this.lockChains.delete(sessionId);
      }
    }
  }
}

function buildTurn(input: Omit<ContextTurn, 'id' | 'tokenUsage' | 'piiDetected' | 'isCompacted'> & { toolName?: string }): ContextTurn {
  return {
    ...input,
    id: `${input.sessionId}_${input.turnId ?? randomUUID()}_${input.turnIndex}`,
    tokenUsage: estimateUsage(input.content),
    piiDetected: detectPII(input.content),
    isCompacted: false
  };
}

function estimateUsage(content: string) {
  const totalTokens = Math.max(1, Math.ceil(content.length / 4));
  return {
    inputTokens: Math.round(totalTokens * 0.6),
    outputTokens: Math.round(totalTokens * 0.4),
    totalTokens,
    estimated: true
  };
}

function detectPII(content: string): boolean {
  const patterns = [
    /\b\d{3}-\d{2}-\d{4}\b/,
    /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
    /\b(?:\+?1[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b/
  ];
  return patterns.some((pattern) => pattern.test(content));
}

function extractFacts(sessionId: string, turns: ContextTurn[]): MemoryFact[] {
  const facts: MemoryFact[] = [];
  const patterns = [
    /(my name is\s+[^.!?\n]+)/i,
    /(i prefer\s+[^.!?\n]+)/i,
    /(remember that\s+[^.!?\n]+)/i,
    /(we decided to\s+[^.!?\n]+)/i
  ];

  for (const turn of turns) {
    for (const pattern of patterns) {
      const match = turn.content.match(pattern);
      if (!match) {
        continue;
      }
      facts.push({
        id: `fact_${randomUUID()}`,
        sessionId,
        fact: match[1].trim(),
        confidence: 0.72,
        sourceTurnId: turn.id,
        createdAt: Date.now(),
        tags: ['long_term_memory', ...autoTags(match[1])]
      });
    }
  }

  return facts;
}

function autoTags(content: string): string[] {
  const lowered = content.toLowerCase();
  const tags = new Set<string>();

  if (/(todo|action item|next step)/.test(lowered)) tags.add('todo');
  if (/(error|exception|failed|failure)/.test(lowered)) tags.add('error');
  if (/(preference|prefer|like)/.test(lowered)) tags.add('preference');
  if (/(deadline|due|schedule|tomorrow|today)/.test(lowered)) tags.add('schedule');
  if (/(tool|api|query|database|sql)/.test(lowered)) tags.add('technical');

  return [...tags];
}

function scoreImportance(content: string, speaker: ContextTurn['speaker']): number {
  let score = speaker === 'user' ? 0.6 : 0.5;
  if (/\bmust\b|\brequired\b|\bcritical\b|\bimportant\b/i.test(content)) score += 0.25;
  if (/\bremember\b|\bpreference\b|\bdecision\b/i.test(content)) score += 0.2;
  if (content.length > 300) score += 0.1;
  return Math.max(0, Math.min(1, score));
}

function quoteForFts(message: string): string {
  const clean = message.replace(/"/g, '');
  const words = clean
    .split(/\s+/)
    .map((word) => word.trim())
    .filter((word) => word.length >= 3)
    .slice(0, 6);

  if (words.length === 0) {
    return '*';
  }

  return words.map((word) => `"${word}"`).join(' OR ');
}

function extractToolName(content: string): string | undefined {
  const match = content.match(/"name"\s*:\s*"([^"]+)"/);
  return match?.[1];
}
