import type { MemoryRetrieval, SearchQuery, SearchResult } from '../types/context.types.js';
import { SQLiteContextStorage } from './storage.js';
export interface ContextSearchOptions {
    defaultLimit?: number;
}
export declare class ContextSearch {
    private readonly storage;
    private readonly options;
    constructor(storage: SQLiteContextStorage, options?: ContextSearchOptions);
    query(input: SearchQuery): Promise<SearchResult[]>;
    retrieveMemory(sessionId: string, query: string, limit?: number): Promise<MemoryRetrieval>;
    private normalize;
}
//# sourceMappingURL=search.d.ts.map