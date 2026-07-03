import type { EngineEvent, QuerySessionState, StateStore } from '../types/core.types.js';
export declare class InMemoryStateStore implements StateStore {
    private readonly sessions;
    private readonly eventsBySession;
    saveSession(session: QuerySessionState): Promise<void>;
    getSession(sessionId: string): Promise<QuerySessionState | null>;
    appendEvent(sessionId: string, event: EngineEvent): Promise<void>;
    getEvents(sessionId: string): Promise<EngineEvent[]>;
    abortSession(sessionId: string): Promise<void>;
}
//# sourceMappingURL=state.d.ts.map