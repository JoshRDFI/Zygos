import Database from 'better-sqlite3';
import { mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { BuildPlanGenerator } from './plan-generator.js';
const TEMPLATES = {
    web_app: {
        projectType: 'web_app',
        name: 'Web Application Interview',
        description: 'Capture frontend, backend, UX, and deployment requirements.',
        baseQuestions: [
            { id: 'web_goal', category: 'goals', text: 'What core user problem should this web app solve?', required: true },
            { id: 'web_users', category: 'users', text: 'Who are the primary user personas and usage frequency?', required: true },
            { id: 'web_features', category: 'features', text: 'Which MVP features are must-have for launch?', required: true },
            { id: 'web_stack', category: 'tech_stack', text: 'Do you have preferred frontend/backend stack or hosting constraints?' },
            { id: 'web_security', category: 'constraints', text: 'Any authentication, security, or compliance requirements?' },
            { id: 'web_timeline', category: 'timeline', text: 'What timeline and release milestone do you need?' }
        ]
    },
    data_pipeline: {
        projectType: 'data_pipeline',
        name: 'Data Pipeline Interview',
        description: 'Capture source systems, data quality, and orchestration constraints.',
        baseQuestions: [
            { id: 'dp_goal', category: 'goals', text: 'What business decision will this pipeline enable?', required: true },
            { id: 'dp_sources', category: 'integration', text: 'Which source systems and update frequencies are required?', required: true },
            { id: 'dp_quality', category: 'validation', text: 'What data quality checks and SLAs should be enforced?', required: true },
            { id: 'dp_stack', category: 'tech_stack', text: 'Preferred orchestration/storage stack (Airflow, dbt, Spark, etc.)?' },
            { id: 'dp_constraints', category: 'constraints', text: 'Any privacy, compliance, or retention constraints?' },
            { id: 'dp_risks', category: 'risks', text: 'What are the top known data dependencies or reliability risks?' }
        ]
    },
    api_service: {
        projectType: 'api_service',
        name: 'API Service Interview',
        description: 'Capture API contracts, SLAs, consumers, and operational requirements.',
        baseQuestions: [
            { id: 'api_goal', category: 'goals', text: 'What business capability should the API provide?', required: true },
            { id: 'api_consumers', category: 'users', text: 'Who are the API consumers and expected traffic patterns?', required: true },
            { id: 'api_contract', category: 'features', text: 'What endpoints/resources and versioning strategy are needed?', required: true },
            { id: 'api_nonfunc', category: 'constraints', text: 'Latency, uptime, auth, and rate limit requirements?' },
            { id: 'api_integrations', category: 'integration', text: 'Which downstream systems must this API integrate with?' },
            { id: 'api_timeline', category: 'timeline', text: 'What launch deadline and rollout stages do you expect?' }
        ]
    },
    tool_utility: {
        projectType: 'tool_utility',
        name: 'Tool/Utility Interview',
        description: 'Capture workflow automation details and edge-case behavior.',
        baseQuestions: [
            { id: 'tool_goal', category: 'goals', text: 'What repetitive workflow should the tool automate?', required: true },
            { id: 'tool_inputs', category: 'features', text: 'What are expected inputs/outputs and formats?', required: true },
            { id: 'tool_users', category: 'users', text: 'Who will run this tool and how often?', required: true },
            { id: 'tool_constraints', category: 'constraints', text: 'Any platform/runtime dependencies or resource constraints?' },
            { id: 'tool_errors', category: 'risks', text: 'What failure modes or edge cases are most important?' }
        ]
    },
    general: {
        projectType: 'general',
        name: 'General Project Interview',
        description: 'Capture goals, scope, constraints, and success criteria.',
        baseQuestions: [
            { id: 'gen_goal', category: 'goals', text: 'What are you trying to build and why now?', required: true },
            { id: 'gen_users', category: 'users', text: 'Who are the stakeholders or target users?', required: true },
            { id: 'gen_features', category: 'features', text: 'What are the top must-have outcomes?', required: true },
            { id: 'gen_constraints', category: 'constraints', text: 'What constraints must we respect (time/budget/compliance)?' },
            { id: 'gen_risks', category: 'risks', text: 'What uncertainties or dependencies worry you most?' }
        ]
    }
};
export class Interviewer {
    deps;
    db = null;
    planGenerator = new BuildPlanGenerator();
    constructor(deps) {
        this.deps = deps;
    }
    async init() {
        if (this.db)
            return;
        await mkdir(dirname(this.deps.dbPath), { recursive: true });
        this.db = new Database(this.deps.dbPath);
        this.db.pragma('journal_mode = WAL');
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS interview_sessions (
        session_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        project_type TEXT NOT NULL,
        title TEXT,
        started_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        completed_at INTEGER,
        payload_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS interview_turns (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        payload_json TEXT,
        FOREIGN KEY(session_id) REFERENCES interview_sessions(session_id)
      );
      CREATE INDEX IF NOT EXISTS idx_interview_turns_session_ts ON interview_turns(session_id, timestamp ASC);
      CREATE TABLE IF NOT EXISTS build_plans (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        markdown TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES interview_sessions(session_id)
      );
      CREATE INDEX IF NOT EXISTS idx_build_plans_session_version ON build_plans(session_id, version DESC);
    `);
    }
    async start(input) {
        await this.init();
        const existing = await this.getSession(input.sessionId);
        if (existing) {
            return this.nextFromSession(existing);
        }
        const projectType = input.forceTemplate ?? input.projectType ?? this.inferProjectType(input.title ?? '');
        const template = this.getTemplate(projectType);
        const now = Date.now();
        const session = {
            id: input.sessionId,
            status: 'active',
            projectType,
            title: input.title,
            startedAt: now,
            updatedAt: now,
            primaryStakeholderId: input.stakeholderId,
            stakeholderIds: input.stakeholderId ? [input.stakeholderId] : [],
            turns: [],
            extractedRequirements: [],
            answeredQuestionIds: [],
            pendingQuestionIds: template.baseQuestions.map((q) => q.id),
            askedClarificationCount: 0,
            maxQuestions: input.maxQuestions ?? this.deps.config.maxQuestions,
            complexitySignal: 0,
            scopeCreepSignal: 0
        };
        await this.persistSession(session);
        return this.nextFromSession(session);
    }
    async answer(sessionId, answer, stakeholderId) {
        await this.init();
        const session = await this.getSession(sessionId);
        if (!session) {
            return this.start({ sessionId, stakeholderId });
        }
        const now = Date.now();
        const lastQuestionTurn = [...session.turns].reverse().find((turn) => turn.role === 'interviewer' && turn.question);
        const questionId = lastQuestionTurn?.question?.id ?? `ad_hoc_${randomUUID()}`;
        const answerTurn = {
            id: `turn_${randomUUID()}`,
            role: 'stakeholder',
            content: answer,
            timestamp: now,
            answer: {
                questionId,
                text: answer,
                stakeholderId,
                answeredAt: now,
                confidence: this.answerConfidence(answer)
            }
        };
        session.turns.push(answerTurn);
        session.updatedAt = now;
        if (stakeholderId && !session.stakeholderIds.includes(stakeholderId)) {
            session.stakeholderIds.push(stakeholderId);
        }
        if (!session.answeredQuestionIds.includes(questionId)) {
            session.answeredQuestionIds.push(questionId);
        }
        session.pendingQuestionIds = session.pendingQuestionIds.filter((id) => id !== questionId);
        this.updateSignals(session, answer);
        await this.persistTurn(session.id, answerTurn);
        await this.persistSession(session);
        return this.nextFromSession(session);
    }
    async complete(sessionId) {
        await this.init();
        const session = await this.getSession(sessionId);
        if (!session)
            return null;
        const plan = this.planGenerator.generate(session);
        await this.persistPlan(plan);
        session.status = 'completed';
        session.completedAt = Date.now();
        session.updatedAt = Date.now();
        session.activePlanId = plan.id;
        await this.persistSession(session);
        return plan;
    }
    async getSession(sessionId) {
        await this.init();
        const row = this.db?.prepare('SELECT payload_json FROM interview_sessions WHERE session_id = ?').get(sessionId);
        if (!row)
            return null;
        const payload = JSON.parse(row.payload_json);
        const turns = this.db
            ?.prepare('SELECT payload_json FROM interview_turns WHERE session_id = ? ORDER BY timestamp ASC')
            .all(sessionId);
        payload.turns = (turns ?? []).map((turn) => JSON.parse(turn.payload_json));
        return payload;
    }
    async getPlan(sessionId) {
        await this.init();
        const row = this.db
            ?.prepare('SELECT payload_json FROM build_plans WHERE session_id = ? ORDER BY version DESC LIMIT 1')
            .get(sessionId);
        return row ? JSON.parse(row.payload_json) : null;
    }
    async exportPlan(sessionId) {
        const plan = await this.getPlan(sessionId);
        if (!plan)
            return null;
        return this.planGenerator.export(plan);
    }
    async shouldGateBuild(userMessage) {
        if (!this.deps.config.enabled || !this.deps.config.requireForComplexBuilds) {
            return { gated: false };
        }
        const complexity = this.estimateMessageComplexity(userMessage);
        if (complexity >= this.deps.config.complexityThreshold) {
            return {
                gated: true,
                reason: `Detected complex request (score=${complexity.toFixed(2)}). Interview required before execution.`
            };
        }
        return { gated: false };
    }
    getMetrics() {
        this.assertDb();
        const sessionsStarted = (this.db?.prepare('SELECT COUNT(1) AS count FROM interview_sessions').get()?.count ?? 0);
        const sessionsCompleted = (this.db
            ?.prepare("SELECT COUNT(1) AS count FROM interview_sessions WHERE status = 'completed'")
            .get()?.count ?? 0);
        const avgTurns = (this.db
            ?.prepare('SELECT AVG(turn_count) AS avg_count FROM (SELECT COUNT(1) AS turn_count FROM interview_turns GROUP BY session_id)')
            .get()?.avg_count ?? 0);
        const avgQuestions = (this.db
            ?.prepare("SELECT AVG(question_count) AS avg_count FROM (SELECT COUNT(1) AS question_count FROM interview_turns WHERE role = 'interviewer' GROUP BY session_id)")
            .get()?.avg_count ?? 0);
        const avgEffort = (this.db?.prepare("SELECT AVG(json_extract(payload_json, '$.estimatedEffortHours')) AS avg_effort FROM build_plans").get()?.avg_effort ?? 0);
        return {
            sessionsStarted,
            sessionsCompleted,
            averageTurnsPerSession: avgTurns,
            averageQuestionsPerSession: avgQuestions,
            averagePlanEffortHours: avgEffort
        };
    }
    async nextFromSession(session) {
        if (this.shouldComplete(session)) {
            const generatedPlan = await this.complete(session.id);
            const updated = await this.getSession(session.id);
            if (!updated) {
                throw new Error('Interview session disappeared after completion.');
            }
            return { session: updated, done: true, generatedPlan: generatedPlan ?? undefined };
        }
        const next = await this.generateNextQuestion(session);
        session.turns.push({
            id: `turn_${randomUUID()}`,
            role: 'interviewer',
            content: next.text,
            timestamp: Date.now(),
            question: next
        });
        session.updatedAt = Date.now();
        await this.persistTurn(session.id, session.turns[session.turns.length - 1]);
        await this.persistSession(session);
        const needsClarification = this.needsClarification(session);
        return {
            session,
            nextQuestion: next,
            done: false,
            needsClarification,
            clarificationPrompt: needsClarification ? 'Could you clarify scope boundaries and key constraints before we continue?' : undefined
        };
    }
    async generateNextQuestion(session) {
        const template = this.getTemplate(session.projectType);
        const remainingBase = template.baseQuestions.filter((q) => !session.answeredQuestionIds.includes(q.id));
        let selected = remainingBase[0];
        if (!selected) {
            selected = this.adaptiveFollowUp(session);
        }
        let text = selected.text;
        if (this.deps.askProvider) {
            const providerSuggestion = await this.safeProviderQuestion(session, selected.text);
            if (providerSuggestion.length > 20) {
                text = providerSuggestion;
            }
        }
        return {
            id: selected.id,
            text,
            category: selected.category,
            required: selected.required,
            askedAt: Date.now()
        };
    }
    adaptiveFollowUp(session) {
        const lastAnswer = [...session.turns].reverse().find((turn) => turn.role === 'stakeholder')?.content ?? '';
        const category = /risk|unknown|dependenc/i.test(lastAnswer)
            ? 'risks'
            : /scope|feature|also|add/i.test(lastAnswer)
                ? 'scope'
                : /integration|api|external/i.test(lastAnswer)
                    ? 'integration'
                    : 'validation';
        const promptByCategory = {
            risks: 'What is your mitigation plan for this risk or dependency?',
            scope: 'Which of these items should be in MVP versus deferred to later phases?',
            integration: 'What are the non-negotiable interfaces and fallback behavior for external dependencies?',
            validation: 'How will we verify success (tests, KPIs, and acceptance criteria)?'
        };
        return {
            id: `followup_${randomUUID()}`,
            category,
            text: promptByCategory[category],
            required: false
        };
    }
    needsClarification(session) {
        const lastAnswer = [...session.turns].reverse().find((turn) => turn.role === 'stakeholder')?.content ?? '';
        return /not sure|depends|maybe|tbd|unknown/i.test(lastAnswer);
    }
    shouldComplete(session) {
        const askedQuestions = session.turns.filter((turn) => turn.role === 'interviewer').length;
        const answered = session.turns.filter((turn) => turn.role === 'stakeholder').length;
        const requiredDone = this.getTemplate(session.projectType).baseQuestions
            .filter((question) => question.required)
            .every((question) => session.answeredQuestionIds.includes(question.id));
        if (askedQuestions >= session.maxQuestions)
            return true;
        if (requiredDone && answered >= Math.min(5, session.maxQuestions))
            return true;
        if (session.scopeCreepSignal > 3 && answered >= 4)
            return true;
        return false;
    }
    updateSignals(session, answer) {
        const lowered = answer.toLowerCase();
        if (/(integration|compliance|auth|latency|scale|migration|security|multi-tenant)/.test(lowered)) {
            session.complexitySignal += 1;
        }
        if (/(also|and another|plus|add|in addition)/.test(lowered)) {
            session.scopeCreepSignal += 1;
        }
    }
    answerConfidence(answer) {
        let score = 0.65;
        if (answer.length > 80)
            score += 0.1;
        if (/(exactly|must|definitely|already decided)/i.test(answer))
            score += 0.1;
        if (/(not sure|depends|maybe|tbd)/i.test(answer))
            score -= 0.25;
        return Math.max(0.1, Math.min(0.98, score));
    }
    inferProjectType(text) {
        const lowered = text.toLowerCase();
        if (/(frontend|react|web app|dashboard|ui)/.test(lowered))
            return 'web_app';
        if (/(pipeline|etl|warehouse|dbt|ingestion)/.test(lowered))
            return 'data_pipeline';
        if (/(api|endpoint|microservice|rest|graphql)/.test(lowered))
            return 'api_service';
        if (/(script|cli|utility|tool|automation)/.test(lowered))
            return 'tool_utility';
        return 'general';
    }
    getTemplate(projectType) {
        if (this.deps.config.template !== 'auto' && TEMPLATES[this.deps.config.template]) {
            return TEMPLATES[this.deps.config.template];
        }
        return TEMPLATES[projectType] ?? TEMPLATES.general;
    }
    estimateMessageComplexity(message) {
        const lowered = message.toLowerCase();
        const signals = [
            /(system|architecture|design)/,
            /(integrat|third-party|provider|api)/,
            /(security|compliance|audit|privacy)/,
            /(real-time|scale|multi-tenant|distributed)/,
            /(workflow|pipeline|orchestration)/,
            /(phase|roadmap|milestone|plan)/
        ];
        const matched = signals.filter((pattern) => pattern.test(lowered)).length;
        const lengthBoost = Math.min(1, message.length / 400);
        return matched + lengthBoost;
    }
    async safeProviderQuestion(session, baseQuestion) {
        try {
            const compactContext = session.turns
                .slice(-4)
                .map((turn) => `${turn.role}: ${turn.content}`)
                .join('\n');
            const prompt = [
                'Rewrite this interviewer question to be concise and context-aware.',
                `Project type: ${session.projectType}`,
                `Base question: ${baseQuestion}`,
                compactContext ? `Recent context:\n${compactContext}` : ''
            ]
                .filter(Boolean)
                .join('\n\n');
            return (await this.deps.askProvider?.(prompt))?.trim() ?? baseQuestion;
        }
        catch (error) {
            // Degrade gracefully to the base question, but record why so the
            // failure is inspectable on the session instead of silently hidden.
            const message = error instanceof Error ? error.message : String(error);
            session.providerWarnings = [
                ...(session.providerWarnings ?? []),
                `askProvider failed; used base question instead: ${message}`
            ];
            return baseQuestion;
        }
    }
    async persistSession(session) {
        this.assertDb();
        this.db
            ?.prepare(`INSERT INTO interview_sessions(session_id, status, project_type, title, started_at, updated_at, completed_at, payload_json)
         VALUES(@session_id, @status, @project_type, @title, @started_at, @updated_at, @completed_at, @payload_json)
         ON CONFLICT(session_id) DO UPDATE SET
           status = excluded.status,
           project_type = excluded.project_type,
           title = excluded.title,
           updated_at = excluded.updated_at,
           completed_at = excluded.completed_at,
           payload_json = excluded.payload_json`)
            .run({
            session_id: session.id,
            status: session.status,
            project_type: session.projectType,
            title: session.title ?? null,
            started_at: session.startedAt,
            updated_at: session.updatedAt,
            completed_at: session.completedAt ?? null,
            payload_json: JSON.stringify(session)
        });
    }
    async persistTurn(sessionId, turn) {
        this.assertDb();
        this.db
            ?.prepare(`INSERT OR REPLACE INTO interview_turns(id, session_id, role, content, timestamp, payload_json)
         VALUES(?, ?, ?, ?, ?, ?)`)
            .run(turn.id, sessionId, turn.role, turn.content, turn.timestamp, JSON.stringify(turn));
    }
    async persistPlan(plan) {
        this.assertDb();
        const existing = this.db
            ?.prepare('SELECT MAX(version) AS version FROM build_plans WHERE session_id = ?')
            .get(plan.sessionId);
        const version = (existing?.version ?? 0) + 1;
        const versioned = { ...plan, version, updatedAt: Date.now() };
        const markdown = this.planGenerator.export(versioned).markdown;
        this.db
            ?.prepare('INSERT INTO build_plans(id, session_id, version, created_at, markdown, payload_json) VALUES(?, ?, ?, ?, ?, ?)')
            .run(versioned.id, versioned.sessionId, versioned.version, Date.now(), markdown, JSON.stringify(versioned));
    }
    assertDb() {
        if (!this.db) {
            throw new Error('Interviewer is not initialized.');
        }
    }
}
export const INTERVIEW_TEMPLATES = TEMPLATES;
//# sourceMappingURL=interviewer.js.map