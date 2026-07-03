import type { ContextManagerLike, ContextPostTurnInput, ContextPreparationResult, ContextSnapshot, CompactionStrategy, SearchQuery, SearchResult } from '../types/context.types.js';
import type { UserTurnInput } from '../types/core.types.js';
import { SQLiteContextStorage } from './storage.js';
export interface ContextManagerOptions {
    defaultModelContextTokens?: number;
    compactionStrategy?: CompactionStrategy;
    maxCachedSnapshots?: number;
    snapshotTtlMs?: number;
}
export declare class ContextManager implements ContextManagerLike {
    private readonly storage;
    private readonly options;
    private readonly budget;
    private readonly compactor;
    private readonly searchService;
    private readonly snapshotCache;
    private readonly logger;
    private readonly metrics;
    private readonly lockChains;
    private initialized;
    constructor(storage: SQLiteContextStorage, options?: ContextManagerOptions);
    init(): Promise<void>;
    prepare(input: UserTurnInput, model?: string): Promise<ContextPreparationResult>;
    postTurnUpdate(input: ContextPostTurnInput): Promise<void>;
    getSnapshot(sessionId: string, model?: string): Promise<ContextSnapshot | null>;
    search(query: SearchQuery): Promise<SearchResult[]>;
    exportSession(sessionId: string, targetPath: string): Promise<void>;
    importSession(sourcePath: string): Promise<void>;
    backupDatabase(targetPath: string): Promise<void>;
    restoreDatabase(sourcePath: string): Promise<void>;
    getMetrics(): import("../providers/observability.js").ContextMetricSnapshot;
    private selectTurns;
    private primeCache;
    private withSessionLock;
}
//# sourceMappingURL=manager.d.ts.map