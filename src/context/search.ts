import type { MemoryRetrieval, SearchQuery, SearchResult } from '../types/context.types.js';
import { SQLiteContextStorage } from './storage.js';

export interface ContextSearchOptions {
  defaultLimit?: number;
}

export class ContextSearch {
  constructor(
    private readonly storage: SQLiteContextStorage,
    private readonly options: ContextSearchOptions = {}
  ) {}

  async query(input: SearchQuery): Promise<SearchResult[]> {
    const normalized = this.normalize(input);
    return this.storage.searchTurns(normalized);
  }

  async retrieveMemory(sessionId: string, query: string, limit = 8): Promise<MemoryRetrieval> {
    const results = await this.query({
      sessionId,
      query,
      limit,
      includeSnippets: true
    });
    const facts = await this.storage.getFacts(sessionId, Math.max(4, Math.floor(limit / 2)));

    return {
      query,
      results,
      facts,
      generatedAt: Date.now()
    };
  }

  private normalize(input: SearchQuery): SearchQuery {
    const limit = Math.max(1, Math.min(100, input.limit ?? this.options.defaultLimit ?? 10));
    const query = normalizeBooleanOperators(input.query);
    const escaped = input.query.trim().length === 0 ? '*' : query;

    return {
      ...input,
      query: escaped,
      limit,
      offset: Math.max(0, input.offset ?? 0)
    };
  }
}

function normalizeBooleanOperators(query: string): string {
  return query
    .replace(/\s+AND\s+/gi, ' AND ')
    .replace(/\s+OR\s+/gi, ' OR ')
    .replace(/\s+NOT\s+/gi, ' NOT ')
    .trim();
}
