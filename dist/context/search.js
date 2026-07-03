import { SQLiteContextStorage } from './storage.js';
export class ContextSearch {
    storage;
    options;
    constructor(storage, options = {}) {
        this.storage = storage;
        this.options = options;
    }
    async query(input) {
        const normalized = this.normalize(input);
        return this.storage.searchTurns(normalized);
    }
    async retrieveMemory(sessionId, query, limit = 8) {
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
    normalize(input) {
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
function normalizeBooleanOperators(query) {
    return query
        .replace(/\s+AND\s+/gi, ' AND ')
        .replace(/\s+OR\s+/gi, ' OR ')
        .replace(/\s+NOT\s+/gi, ' NOT ')
        .trim();
}
//# sourceMappingURL=search.js.map