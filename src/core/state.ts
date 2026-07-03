import type { EngineEvent, QuerySessionState, StateStore } from '../types/core.types.js';

export class InMemoryStateStore implements StateStore {
  private readonly sessions = new Map<string, QuerySessionState>();

  private readonly eventsBySession = new Map<string, EngineEvent[]>();

  async saveSession(session: QuerySessionState): Promise<void> {
    this.sessions.set(session.sessionId, { ...session, updatedAt: Date.now() });
  }

  async getSession(sessionId: string): Promise<QuerySessionState | null> {
    return this.sessions.get(sessionId) ?? null;
  }

  async appendEvent(sessionId: string, event: EngineEvent): Promise<void> {
    const events = this.eventsBySession.get(sessionId) ?? [];
    events.push(event);
    this.eventsBySession.set(sessionId, events);
  }

  async getEvents(sessionId: string): Promise<EngineEvent[]> {
    return this.eventsBySession.get(sessionId) ?? [];
  }

  async abortSession(sessionId: string): Promise<void> {
    this.sessions.delete(sessionId);
    this.eventsBySession.delete(sessionId);
  }
}
