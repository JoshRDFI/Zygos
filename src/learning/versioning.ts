import Database from 'better-sqlite3';
import { mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import type {
  ABTestRecord,
  LearningAuditEntry,
  LearningPersistence,
  LearningProposal,
  LearningProposalStatus,
  LearningState,
  ToolExecutionObservation,
  ToolVersionRecord
} from '../types/learning.types.js';

const DEFAULT_STATE: LearningState = {
  enabled: true,
  approvalMode: 'manual',
  metrics: {
    observedExecutions: 0,
    proposalsCreated: 0,
    proposalsApplied: 0,
    proposalsRejected: 0,
    rollbacks: 0,
    averageSuccessRateGain: 0,
    averageLatencyGainMs: 0
  },
  recommendations: []
};

interface SQLiteVersioningOptions {
  dbPath: string;
}

export class SQLiteLearningStore implements LearningPersistence {
  private db: Database.Database | null = null;

  constructor(private readonly options: SQLiteVersioningOptions) {}

  async init(): Promise<void> {
    await mkdir(dirname(this.options.dbPath), { recursive: true });
    this.db = new Database(this.options.dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('synchronous = NORMAL');
    this.db.pragma('busy_timeout = 5000');
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS learning_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        tool_call_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        tool_call_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        context_tags_json TEXT,
        context_snapshot_json TEXT,
        created_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS learning_proposals (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        risk TEXT NOT NULL,
        source TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        approved_by TEXT,
        payload_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS tool_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_name TEXT NOT NULL,
        version TEXT NOT NULL,
        branch TEXT NOT NULL,
        reason TEXT NOT NULL,
        actor TEXT NOT NULL,
        change_type TEXT NOT NULL,
        definition_json TEXT NOT NULL,
        metrics_json TEXT,
        parent_version_id INTEGER,
        is_stable INTEGER NOT NULL DEFAULT 0,
        tags_json TEXT NOT NULL DEFAULT '[]',
        created_at INTEGER NOT NULL
      );

      CREATE INDEX IF NOT EXISTS idx_tool_versions_name_branch ON tool_versions(tool_name, branch, id DESC);

      CREATE TABLE IF NOT EXISTS learning_ab_tests (
        id TEXT PRIMARY KEY,
        tool_name TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS learning_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        details_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS learning_state (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
      );
    `);

    const existing = this.db.prepare('SELECT value_json FROM learning_state WHERE key = ?').get('state') as
      | { value_json: string }
      | undefined;
    if (!existing) {
      this.db
        .prepare('INSERT INTO learning_state(key, value_json, updated_at) VALUES (?, ?, ?)')
        .run('state', JSON.stringify(DEFAULT_STATE), Date.now());
    }
  }

  async close(): Promise<void> {
    this.db?.close();
    this.db = null;
  }

  async recordObservation(observation: ToolExecutionObservation): Promise<void> {
    const db = this.requireDb();
    db.prepare(
      `INSERT INTO learning_observations(
        session_id, turn_id, tool_call_id, tool_name, tool_call_json, result_json, context_tags_json, context_snapshot_json, created_at
      ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      observation.sessionId,
      observation.turnId,
      observation.toolCall.id,
      observation.toolCall.name,
      JSON.stringify(observation.toolCall),
      JSON.stringify(observation.result),
      JSON.stringify(observation.contextTags ?? []),
      observation.contextSnapshot ? JSON.stringify(observation.contextSnapshot) : null,
      observation.createdAt
    );
  }

  async getRecentObservations(limit: number): Promise<ToolExecutionObservation[]> {
    const db = this.requireDb();
    const rows = db
      .prepare(
        'SELECT * FROM learning_observations ORDER BY id DESC LIMIT ?'
      )
      .all(Math.max(1, limit)) as Array<{
      id: number;
      session_id: string;
      turn_id: string;
      tool_call_json: string;
      result_json: string;
      context_tags_json: string | null;
      context_snapshot_json: string | null;
      created_at: number;
    }>;

    return rows.map((row) => ({
      id: row.id,
      sessionId: row.session_id,
      turnId: row.turn_id,
      toolCall: JSON.parse(row.tool_call_json),
      result: JSON.parse(row.result_json),
      contextTags: row.context_tags_json ? JSON.parse(row.context_tags_json) : [],
      contextSnapshot: row.context_snapshot_json ? JSON.parse(row.context_snapshot_json) : undefined,
      createdAt: row.created_at
    }));
  }

  async saveProposal(proposal: LearningProposal): Promise<void> {
    const db = this.requireDb();
    db.prepare(
      `INSERT OR REPLACE INTO learning_proposals(
         id, kind, status, risk, source, requested_by, approved_by, payload_json, created_at, updated_at
       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      proposal.id,
      proposal.kind,
      proposal.status,
      proposal.risk,
      proposal.source,
      proposal.requestedBy,
      proposal.approvedBy ?? null,
      JSON.stringify(proposal.payload),
      proposal.createdAt,
      proposal.updatedAt
    );
  }

  async listProposals(status?: LearningProposalStatus): Promise<LearningProposal[]> {
    const db = this.requireDb();
    const rows = status
      ? db.prepare('SELECT * FROM learning_proposals WHERE status = ? ORDER BY created_at DESC').all(status)
      : db.prepare('SELECT * FROM learning_proposals ORDER BY created_at DESC').all();

    return (rows as Array<Record<string, unknown>>).map((row) => ({
      id: String(row.id),
      kind: row.kind as LearningProposal['kind'],
      status: row.status as LearningProposal['status'],
      risk: row.risk as LearningProposal['risk'],
      source: row.source as LearningProposal['source'],
      requestedBy: String(row.requested_by),
      approvedBy: row.approved_by ? String(row.approved_by) : undefined,
      payload: JSON.parse(String(row.payload_json)),
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at)
    }));
  }

  async updateProposalStatus(id: string, status: LearningProposalStatus, approvedBy?: string): Promise<void> {
    const db = this.requireDb();
    db.prepare('UPDATE learning_proposals SET status = ?, approved_by = COALESCE(?, approved_by), updated_at = ? WHERE id = ?').run(
      status,
      approvedBy ?? null,
      Date.now(),
      id
    );
  }

  async saveVersion(record: Omit<ToolVersionRecord, 'id'>): Promise<ToolVersionRecord> {
    const db = this.requireDb();
    const info = db
      .prepare(
        `INSERT INTO tool_versions(
           tool_name, version, branch, reason, actor, change_type, definition_json, metrics_json, parent_version_id, is_stable, tags_json, created_at
         ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        record.toolName,
        record.version,
        record.branch,
        record.reason,
        record.actor,
        record.changeType,
        JSON.stringify(record.definition),
        record.metrics ? JSON.stringify(record.metrics) : null,
        record.parentVersionId ?? null,
        record.isStable ? 1 : 0,
        JSON.stringify(record.tags),
        record.createdAt
      );

    return { ...record, id: Number(info.lastInsertRowid) };
  }

  async listVersions(toolName: string, branch = 'main'): Promise<ToolVersionRecord[]> {
    const db = this.requireDb();
    const rows = db
      .prepare('SELECT * FROM tool_versions WHERE tool_name = ? AND branch = ? ORDER BY id DESC')
      .all(toolName, branch) as Array<Record<string, unknown>>;

    return rows.map((row) => ({
      id: Number(row.id),
      toolName: String(row.tool_name),
      version: String(row.version),
      branch: String(row.branch),
      reason: String(row.reason),
      actor: String(row.actor),
      changeType: row.change_type as ToolVersionRecord['changeType'],
      definition: JSON.parse(String(row.definition_json)),
      metrics: row.metrics_json ? JSON.parse(String(row.metrics_json)) : undefined,
      parentVersionId: row.parent_version_id ? Number(row.parent_version_id) : undefined,
      isStable: Number(row.is_stable) === 1,
      tags: JSON.parse(String(row.tags_json)),
      createdAt: Number(row.created_at)
    }));
  }

  async saveABTest(record: ABTestRecord): Promise<void> {
    const db = this.requireDb();
    db.prepare('INSERT OR REPLACE INTO learning_ab_tests(id, tool_name, payload_json, created_at) VALUES(?, ?, ?, ?)').run(
      record.id,
      record.toolName,
      JSON.stringify(record),
      record.createdAt
    );
  }

  async appendAudit(entry: LearningAuditEntry): Promise<void> {
    const db = this.requireDb();
    db.prepare('INSERT INTO learning_audit(action, entity_type, entity_id, details_json, created_at) VALUES(?, ?, ?, ?, ?)').run(
      entry.action,
      entry.entityType,
      entry.entityId,
      JSON.stringify(entry.details),
      entry.createdAt
    );
  }

  async readState(): Promise<LearningState> {
    const db = this.requireDb();
    const row = db.prepare('SELECT value_json FROM learning_state WHERE key = ?').get('state') as
      | { value_json: string }
      | undefined;
    if (!row) {
      return DEFAULT_STATE;
    }
    return JSON.parse(row.value_json) as LearningState;
  }

  async writeState(state: LearningState): Promise<void> {
    const db = this.requireDb();
    db.prepare('INSERT OR REPLACE INTO learning_state(key, value_json, updated_at) VALUES(?, ?, ?)').run(
      'state',
      JSON.stringify(state),
      Date.now()
    );
  }

  private requireDb(): Database.Database {
    if (!this.db) {
      throw new Error('SQLiteLearningStore is not initialized.');
    }
    return this.db;
  }
}

export function diffToolVersions(before: ToolVersionRecord, after: ToolVersionRecord): Array<{ path: string; before: unknown; after: unknown }> {
  const changes: Array<{ path: string; before: unknown; after: unknown }> = [];
  const walk = (prefix: string, a: unknown, b: unknown) => {
    if (JSON.stringify(a) === JSON.stringify(b)) {
      return;
    }
    if (typeof a !== 'object' || a === null || typeof b !== 'object' || b === null) {
      changes.push({ path: prefix, before: a, after: b });
      return;
    }

    const keys = new Set([...Object.keys(a as Record<string, unknown>), ...Object.keys(b as Record<string, unknown>)]);
    for (const key of keys) {
      const nextPrefix = prefix ? `${prefix}.${key}` : key;
      walk(nextPrefix, (a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]);
    }
  };

  walk('', before.definition, after.definition);
  return changes;
}
