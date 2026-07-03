import type { ABTestRecord, LearningAuditEntry, LearningPersistence, LearningProposal, LearningProposalStatus, LearningState, ToolExecutionObservation, ToolVersionRecord } from '../types/learning.types.js';
interface SQLiteVersioningOptions {
    dbPath: string;
}
export declare class SQLiteLearningStore implements LearningPersistence {
    private readonly options;
    private db;
    constructor(options: SQLiteVersioningOptions);
    init(): Promise<void>;
    close(): Promise<void>;
    recordObservation(observation: ToolExecutionObservation): Promise<void>;
    getRecentObservations(limit: number): Promise<ToolExecutionObservation[]>;
    saveProposal(proposal: LearningProposal): Promise<void>;
    listProposals(status?: LearningProposalStatus): Promise<LearningProposal[]>;
    updateProposalStatus(id: string, status: LearningProposalStatus, approvedBy?: string): Promise<void>;
    saveVersion(record: Omit<ToolVersionRecord, 'id'>): Promise<ToolVersionRecord>;
    listVersions(toolName: string, branch?: string): Promise<ToolVersionRecord[]>;
    saveABTest(record: ABTestRecord): Promise<void>;
    appendAudit(entry: LearningAuditEntry): Promise<void>;
    readState(): Promise<LearningState>;
    writeState(state: LearningState): Promise<void>;
    private requireDb;
}
export declare function diffToolVersions(before: ToolVersionRecord, after: ToolVersionRecord): Array<{
    path: string;
    before: unknown;
    after: unknown;
}>;
export {};
//# sourceMappingURL=versioning.d.ts.map