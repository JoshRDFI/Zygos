import type { ContextTurn, MemoryFact, SearchQuery, SearchResult } from '../types/context.types.js';
export interface SQLiteStorageOptions {
    dbPath: string;
    readPoolSize?: number;
}
export declare class SQLiteContextStorage {
    private readonly options;
    private writeDb;
    private readDbs;
    private readIndex;
    private writeChain;
    constructor(options: SQLiteStorageOptions);
    init(): Promise<void>;
    close(): Promise<void>;
    upsertSession(sessionId: string, title?: string, tags?: string[]): Promise<void>;
    saveTurn(turn: ContextTurn): Promise<void>;
    saveTurns(turns: ContextTurn[]): Promise<void>;
    getRecentTurns(sessionId: string, limit?: number, includeCompacted?: boolean): Promise<ContextTurn[]>;
    getTurns(sessionId: string, includeCompacted?: boolean): Promise<ContextTurn[]>;
    markTurnsCompacted(sessionId: string, turnIds: string[]): Promise<void>;
    getSessionTurnCount(sessionId: string): Promise<number>;
    searchTurns(query: SearchQuery): Promise<SearchResult[]>;
    saveFacts(facts: MemoryFact[]): Promise<void>;
    getFacts(sessionId: string, limit?: number): Promise<MemoryFact[]>;
    backupTo(targetPath: string): Promise<void>;
    restoreFrom(sourcePath: string): Promise<void>;
    private runMigrations;
    private pickReadDb;
    private requireWriteDb;
    private enqueueWrite;
    private toContextTurn;
}
//# sourceMappingURL=storage.d.ts.map