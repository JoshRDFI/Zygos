import Database from 'better-sqlite3';
import { copyFile, mkdir, stat } from 'node:fs/promises';
import { dirname } from 'node:path';
const MIGRATIONS = [
    {
        id: 1,
        name: 'initial_context_schema',
        sql: `
      CREATE TABLE IF NOT EXISTS schema_migrations (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        title TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]'
      );

      CREATE TABLE IF NOT EXISTS turns (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE,
        session_id TEXT NOT NULL,
        turn_id TEXT,
        turn_index INTEGER NOT NULL,
        speaker TEXT NOT NULL,
        content_type TEXT NOT NULL,
        content TEXT NOT NULL,
        content_hash TEXT,
        model TEXT,
        provider TEXT,
        tool_name TEXT,
        token_input INTEGER,
        token_output INTEGER,
        token_total INTEGER,
        importance_score REAL NOT NULL DEFAULT 0.5,
        tags_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT,
        summary_of_turn_ids_json TEXT,
        pii_detected INTEGER NOT NULL DEFAULT 0,
        is_compacted INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
      );

      CREATE INDEX IF NOT EXISTS idx_turns_session_index ON turns(session_id, turn_index DESC);
      CREATE INDEX IF NOT EXISTS idx_turns_created_at ON turns(created_at DESC);
      CREATE INDEX IF NOT EXISTS idx_turns_speaker ON turns(speaker);
      CREATE INDEX IF NOT EXISTS idx_turns_content_type ON turns(content_type);

      CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
        content,
        tags,
        session_id UNINDEXED,
        turn_ref UNINDEXED,
        tokenize = 'porter unicode61'
      );

      CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        fact TEXT NOT NULL,
        confidence REAL NOT NULL,
        source_turn_id TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        created_at INTEGER NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
      );

      CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id, created_at DESC);

      CREATE TABLE IF NOT EXISTS conversation_clusters (
        cluster_id TEXT PRIMARY KEY,
        centroid_terms TEXT NOT NULL,
        session_count INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS session_cluster_links (
        session_id TEXT NOT NULL,
        cluster_id TEXT NOT NULL,
        score REAL NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY(session_id, cluster_id)
      );
    `
    }
];
export class SQLiteContextStorage {
    options;
    writeDb = null;
    readDbs = [];
    readIndex = 0;
    writeChain = Promise.resolve();
    constructor(options) {
        this.options = options;
    }
    async init() {
        await mkdir(dirname(this.options.dbPath), { recursive: true });
        this.writeDb = new Database(this.options.dbPath);
        this.writeDb.pragma('journal_mode = WAL');
        this.writeDb.pragma('synchronous = NORMAL');
        this.writeDb.pragma('busy_timeout = 5000');
        this.writeDb.pragma('foreign_keys = ON');
        this.runMigrations(this.writeDb);
        const poolSize = Math.max(1, this.options.readPoolSize ?? 2);
        this.readDbs = Array.from({ length: poolSize }).map(() => {
            const db = new Database(this.options.dbPath, { readonly: true });
            db.pragma('busy_timeout = 5000');
            return db;
        });
    }
    async close() {
        for (const db of this.readDbs) {
            db.close();
        }
        this.readDbs = [];
        this.writeDb?.close();
        this.writeDb = null;
    }
    async upsertSession(sessionId, title, tags = []) {
        await this.enqueueWrite(async () => {
            const db = this.requireWriteDb();
            const now = Date.now();
            const stmt = db.prepare(`
        INSERT INTO sessions(session_id, title, created_at, updated_at, tags_json)
        VALUES(@session_id, @title, @created_at, @updated_at, @tags_json)
        ON CONFLICT(session_id) DO UPDATE SET
          title = COALESCE(excluded.title, sessions.title),
          updated_at = excluded.updated_at,
          tags_json = excluded.tags_json
      `);
            stmt.run({
                session_id: sessionId,
                title: title ?? null,
                created_at: now,
                updated_at: now,
                tags_json: JSON.stringify(tags)
            });
        });
    }
    async saveTurn(turn) {
        await this.saveTurns([turn]);
    }
    async saveTurns(turns) {
        if (turns.length === 0) {
            return;
        }
        await this.enqueueWrite(async () => {
            const db = this.requireWriteDb();
            const insertTurn = db.prepare(`
        INSERT OR REPLACE INTO turns(
          id, session_id, turn_id, turn_index, speaker, content_type, content,
          model, provider, tool_name, token_input, token_output, token_total,
          importance_score, tags_json, metadata_json, summary_of_turn_ids_json,
          pii_detected, is_compacted, created_at, updated_at
        )
        VALUES(
          @id, @session_id, @turn_id, @turn_index, @speaker, @content_type, @content,
          @model, @provider, @tool_name, @token_input, @token_output, @token_total,
          @importance_score, @tags_json, @metadata_json, @summary_of_turn_ids_json,
          @pii_detected, @is_compacted, @created_at, @updated_at
        )
      `);
            const deleteFts = db.prepare('DELETE FROM turns_fts WHERE turn_ref = ?');
            const insertFts = db.prepare('INSERT INTO turns_fts(content, tags, session_id, turn_ref) VALUES (?, ?, ?, ?)');
            const runTxn = db.transaction((items) => {
                for (const turn of items) {
                    insertTurn.run({
                        id: turn.id,
                        session_id: turn.sessionId,
                        turn_id: turn.turnId ?? null,
                        turn_index: turn.turnIndex,
                        speaker: turn.speaker,
                        content_type: turn.contentType,
                        content: turn.content,
                        model: turn.model ?? null,
                        provider: turn.provider ?? null,
                        tool_name: turn.toolName ?? null,
                        token_input: turn.tokenUsage?.inputTokens ?? null,
                        token_output: turn.tokenUsage?.outputTokens ?? null,
                        token_total: turn.tokenUsage?.totalTokens ?? null,
                        importance_score: turn.importanceScore,
                        tags_json: JSON.stringify(turn.tags),
                        metadata_json: turn.metadata ? JSON.stringify(turn.metadata) : null,
                        summary_of_turn_ids_json: turn.summaryOfTurnIds ? JSON.stringify(turn.summaryOfTurnIds) : null,
                        pii_detected: turn.piiDetected ? 1 : 0,
                        is_compacted: turn.isCompacted ? 1 : 0,
                        created_at: turn.createdAt,
                        updated_at: turn.updatedAt
                    });
                    deleteFts.run(turn.id);
                    insertFts.run(turn.content, turn.tags.join(' '), turn.sessionId, turn.id);
                }
            });
            runTxn(turns);
            const sessionId = turns[0].sessionId;
            const mostRecent = turns.reduce((latest, turn) => Math.max(latest, turn.updatedAt), 0);
            db.prepare(`INSERT INTO sessions(session_id, created_at, updated_at, tags_json)
         VALUES(?, ?, ?, '[]')
         ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at`).run(sessionId, mostRecent, mostRecent);
        });
    }
    async getRecentTurns(sessionId, limit = 30, includeCompacted = true) {
        const db = this.pickReadDb();
        const query = includeCompacted
            ? 'SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index DESC LIMIT ?'
            : 'SELECT * FROM turns WHERE session_id = ? AND is_compacted = 0 ORDER BY turn_index DESC LIMIT ?';
        const rows = db.prepare(query).all(sessionId, limit);
        return rows.map((row) => this.toContextTurn(row));
    }
    async getTurns(sessionId, includeCompacted = true) {
        const db = this.pickReadDb();
        const query = includeCompacted
            ? 'SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index ASC'
            : 'SELECT * FROM turns WHERE session_id = ? AND is_compacted = 0 ORDER BY turn_index ASC';
        const rows = db.prepare(query).all(sessionId);
        return rows.map((row) => this.toContextTurn(row));
    }
    async markTurnsCompacted(sessionId, turnIds) {
        if (turnIds.length === 0) {
            return;
        }
        await this.enqueueWrite(async () => {
            const db = this.requireWriteDb();
            const stmt = db.prepare('UPDATE turns SET is_compacted = 1, updated_at = ? WHERE session_id = ? AND id = ?');
            const now = Date.now();
            const tx = db.transaction((ids) => {
                for (const id of ids) {
                    stmt.run(now, sessionId, id);
                }
            });
            tx(turnIds);
        });
    }
    async getSessionTurnCount(sessionId) {
        const db = this.pickReadDb();
        const row = db.prepare('SELECT COUNT(1) AS count FROM turns WHERE session_id = ?').get(sessionId);
        return row.count;
    }
    async searchTurns(query) {
        const db = this.pickReadDb();
        const limit = Math.max(1, Math.min(100, query.limit ?? 10));
        const offset = Math.max(0, query.offset ?? 0);
        const conditions = ['turns_fts MATCH @fts_query'];
        if (query.sessionId) {
            conditions.push('turns.session_id = @session_id');
        }
        if (query.speaker) {
            conditions.push('turns.speaker = @speaker');
        }
        if (query.contentType) {
            conditions.push('turns.content_type = @content_type');
        }
        if (query.fromTs) {
            conditions.push('turns.created_at >= @from_ts');
        }
        if (query.toTs) {
            conditions.push('turns.created_at <= @to_ts');
        }
        const snippetExpr = query.includeSnippets
            ? "snippet(turns_fts, 0, '[', ']', '…', 18) AS snippet"
            : 'NULL AS snippet';
        const sql = `
      SELECT turns.*, bm25(turns_fts, 5.0, 1.0) AS rank, ${snippetExpr}
      FROM turns_fts
      JOIN turns ON turns.id = turns_fts.turn_ref
      WHERE ${conditions.join(' AND ')}
      ORDER BY rank, turns.created_at DESC
      LIMIT @limit OFFSET @offset
    `;
        const rows = db.prepare(sql).all({
            fts_query: query.query,
            session_id: query.sessionId,
            speaker: query.speaker,
            content_type: query.contentType,
            from_ts: query.fromTs,
            to_ts: query.toTs,
            limit,
            offset
        });
        return rows.map((row) => ({
            turn: this.toContextTurn(row),
            rank: row.rank,
            snippet: row.snippet ?? undefined,
            highlights: row.snippet ? [...row.snippet.matchAll(/\[(.*?)\]/g)].map((m) => m[1]) : []
        }));
    }
    async saveFacts(facts) {
        if (facts.length === 0) {
            return;
        }
        await this.enqueueWrite(async () => {
            const db = this.requireWriteDb();
            const stmt = db.prepare(`
        INSERT OR REPLACE INTO memories(id, session_id, fact, confidence, source_turn_id, tags_json, created_at)
        VALUES(@id, @session_id, @fact, @confidence, @source_turn_id, @tags_json, @created_at)
      `);
            const tx = db.transaction((items) => {
                for (const fact of items) {
                    stmt.run({
                        id: fact.id,
                        session_id: fact.sessionId,
                        fact: fact.fact,
                        confidence: fact.confidence,
                        source_turn_id: fact.sourceTurnId,
                        tags_json: JSON.stringify(fact.tags),
                        created_at: fact.createdAt
                    });
                }
            });
            tx(facts);
        });
    }
    async getFacts(sessionId, limit = 20) {
        const db = this.pickReadDb();
        const rows = db
            .prepare('SELECT * FROM memories WHERE session_id = ? ORDER BY confidence DESC, created_at DESC LIMIT ?')
            .all(sessionId, limit);
        return rows.map((row) => ({
            id: row.id,
            sessionId: row.session_id,
            fact: row.fact,
            confidence: row.confidence,
            sourceTurnId: row.source_turn_id,
            createdAt: row.created_at,
            tags: parseJson(row.tags_json, [])
        }));
    }
    async backupTo(targetPath) {
        await this.enqueueWrite(async () => {
            const db = this.requireWriteDb();
            await mkdir(dirname(targetPath), { recursive: true });
            db.prepare('VACUUM INTO ?').run(targetPath);
        });
    }
    async restoreFrom(sourcePath) {
        await stat(sourcePath);
        await this.close();
        await mkdir(dirname(this.options.dbPath), { recursive: true });
        await copyFile(sourcePath, this.options.dbPath);
        await this.init();
    }
    runMigrations(db) {
        db.exec('CREATE TABLE IF NOT EXISTS schema_migrations (id INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL)');
        const existingRows = db.prepare('SELECT id FROM schema_migrations').all();
        const applied = new Set(existingRows.map((row) => row.id));
        for (const migration of MIGRATIONS) {
            if (applied.has(migration.id)) {
                continue;
            }
            const tx = db.transaction(() => {
                db.exec(migration.sql);
                db.prepare('INSERT INTO schema_migrations(id, name, applied_at) VALUES (?, ?, ?)').run(migration.id, migration.name, Date.now());
            });
            tx();
        }
    }
    pickReadDb() {
        if (this.readDbs.length === 0) {
            return this.requireWriteDb();
        }
        const db = this.readDbs[this.readIndex % this.readDbs.length];
        this.readIndex += 1;
        return db;
    }
    requireWriteDb() {
        if (!this.writeDb) {
            throw new Error('SQLiteContextStorage is not initialized.');
        }
        return this.writeDb;
    }
    async enqueueWrite(fn) {
        const run = this.writeChain.then(() => fn());
        this.writeChain = run.then(() => undefined, () => undefined);
        return run;
    }
    toContextTurn(row) {
        return {
            id: row.id,
            sessionId: row.session_id,
            turnId: row.turn_id ?? undefined,
            turnIndex: row.turn_index,
            speaker: row.speaker,
            contentType: row.content_type,
            content: row.content,
            toolName: row.tool_name ?? undefined,
            model: row.model ?? undefined,
            provider: row.provider ?? undefined,
            createdAt: row.created_at,
            updatedAt: row.updated_at,
            tokenUsage: row.token_total === null
                ? undefined
                : {
                    inputTokens: row.token_input ?? 0,
                    outputTokens: row.token_output ?? 0,
                    totalTokens: row.token_total,
                    estimated: true
                },
            importanceScore: row.importance_score,
            tags: parseJson(row.tags_json, []),
            metadata: row.metadata_json ? parseJson(row.metadata_json, {}) : undefined,
            summaryOfTurnIds: row.summary_of_turn_ids_json ? parseJson(row.summary_of_turn_ids_json, []) : undefined,
            piiDetected: row.pii_detected === 1,
            isCompacted: row.is_compacted === 1
        };
    }
}
function parseJson(value, fallback) {
    try {
        return JSON.parse(value);
    }
    catch {
        return fallback;
    }
}
//# sourceMappingURL=storage.js.map