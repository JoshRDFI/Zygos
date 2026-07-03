export class InMemoryStateStore {
    sessions = new Map();
    eventsBySession = new Map();
    async saveSession(session) {
        this.sessions.set(session.sessionId, { ...session, updatedAt: Date.now() });
    }
    async getSession(sessionId) {
        return this.sessions.get(sessionId) ?? null;
    }
    async appendEvent(sessionId, event) {
        const events = this.eventsBySession.get(sessionId) ?? [];
        events.push(event);
        this.eventsBySession.set(sessionId, events);
    }
    async getEvents(sessionId) {
        return this.eventsBySession.get(sessionId) ?? [];
    }
    async abortSession(sessionId) {
        this.sessions.delete(sessionId);
        this.eventsBySession.delete(sessionId);
    }
}
//# sourceMappingURL=state.js.map