import { randomUUID } from 'node:crypto';
const PRIORITY_ORDER = ['must', 'should', 'could'];
function detectPriority(text) {
    const lowered = text.toLowerCase();
    if (/(must|required|critical|non-negotiable|need to)/.test(lowered))
        return 'must';
    if (/(nice to have|optional|could|eventually)/.test(lowered))
        return 'could';
    return 'should';
}
function detectComplexity(input) {
    const score = input.requirements * 1.2 + input.constraints * 1.5 + input.risks * 1.3 + input.integrations * 1.7;
    if (score >= 18)
        return 'high';
    if (score >= 9)
        return 'medium';
    return 'low';
}
function effortMultiplier(complexity) {
    if (complexity === 'high')
        return 5;
    if (complexity === 'medium')
        return 3;
    return 1.75;
}
function categoryForTurn(content) {
    const lowered = content.toLowerCase();
    if (/(timeline|deadline|milestone)/.test(lowered))
        return 'timeline';
    if (/(constraint|budget|compliance|legal|security|privacy)/.test(lowered))
        return 'constraints';
    if (/(risk|unknown|uncertain|blocker)/.test(lowered))
        return 'risks';
    if (/(integrat|third-party|external|api)/.test(lowered))
        return 'integration';
    if (/(stack|framework|language|database|cloud|deploy)/.test(lowered))
        return 'tech_stack';
    if (/(user|persona|audience|customer)/.test(lowered))
        return 'users';
    if (/(goal|success|outcome)/.test(lowered))
        return 'goals';
    return 'features';
}
export class BuildPlanGenerator {
    generate(session) {
        const stakeholderTurns = session.turns.filter((turn) => turn.role === 'stakeholder');
        const requirements = this.extractRequirements(stakeholderTurns);
        const constraints = this.extractConstraints(stakeholderTurns);
        const risks = this.extractRisks(stakeholderTurns);
        const assumptions = this.extractAssumptions(stakeholderTurns);
        const unresolvedQuestions = this.extractUnresolvedQuestions(session);
        const integrations = stakeholderTurns.filter((turn) => /integrat|third-party|api/i.test(turn.content)).length;
        const complexity = detectComplexity({
            requirements: requirements.length,
            constraints: constraints.length,
            risks: risks.length,
            integrations
        });
        const roadmap = this.buildRoadmap(session.projectType, requirements, complexity, risks);
        const estimatedEffortHours = roadmap.flatMap((phase) => phase.tasks).reduce((sum, task) => sum + task.effortHours, 0);
        return {
            id: `plan_${randomUUID()}`,
            sessionId: session.id,
            version: 1,
            createdAt: Date.now(),
            updatedAt: Date.now(),
            projectType: session.projectType,
            summary: this.buildSummary(session.projectType, requirements, complexity),
            requirements,
            constraints,
            assumptions,
            risks,
            recommendations: this.recommendationsFor(session.projectType, complexity, constraints, risks),
            complexity,
            estimatedEffortHours,
            roadmap,
            unresolvedQuestions
        };
    }
    export(plan) {
        const markdown = [
            `# Build Plan: ${plan.projectType}`,
            '',
            `- **Plan ID:** ${plan.id}`,
            `- **Complexity:** ${plan.complexity}`,
            `- **Estimated Effort:** ${plan.estimatedEffortHours}h`,
            '',
            '## Summary',
            plan.summary,
            '',
            '## Requirements',
            ...plan.requirements.map((req) => `- [${req.priority.toUpperCase()}] **${req.title}**: ${req.description}`),
            '',
            '## Constraints',
            ...(plan.constraints.length > 0 ? plan.constraints.map((c) => `- ${c}`) : ['- None captured']),
            '',
            '## Risks',
            ...(plan.risks.length > 0 ? plan.risks.map((risk) => `- ${risk}`) : ['- No critical risks captured']),
            '',
            '## Roadmap',
            ...plan.roadmap.flatMap((phase) => [
                `### ${phase.title}`,
                phase.objective,
                ...phase.tasks.map((task) => `- (${task.priority}) ${task.title} — ${task.description} _(effort: ${task.effortHours}h, complexity: ${task.complexity})_`),
                ''
            ])
        ].join('\n');
        return { json: plan, markdown };
    }
    extractRequirements(turns) {
        return turns.slice(0, 16).map((turn) => {
            const category = categoryForTurn(turn.content);
            const priority = detectPriority(turn.content);
            const title = turn.content.split(/[.!?\n]/)[0].slice(0, 90) || 'Captured requirement';
            return {
                id: `req_${randomUUID()}`,
                title,
                description: turn.content,
                priority,
                category,
                sourceTurnId: turn.id,
                assumptions: /assume|assuming/i.test(turn.content) ? [turn.content] : [],
                acceptanceCriteria: this.inferAcceptanceCriteria(turn.content)
            };
        });
    }
    extractConstraints(turns) {
        return turns
            .filter((turn) => /(constraint|must not|cannot|budget|deadline|compliance|security|privacy)/i.test(turn.content))
            .map((turn) => turn.content)
            .slice(0, 10);
    }
    extractRisks(turns) {
        return turns
            .filter((turn) => /(risk|unknown|unsure|not sure|dependency|blocker|migration)/i.test(turn.content))
            .map((turn) => turn.content)
            .slice(0, 10);
    }
    extractAssumptions(turns) {
        return turns
            .filter((turn) => /(assume|assuming|probably|likely|expect)/i.test(turn.content))
            .map((turn) => turn.content)
            .slice(0, 8);
    }
    extractUnresolvedQuestions(session) {
        const questionTurns = session.turns.filter((turn) => turn.question);
        return questionTurns
            .filter((turn) => !session.answeredQuestionIds.includes(turn.question?.id ?? ''))
            .map((turn) => turn.content)
            .slice(0, 6);
    }
    buildSummary(projectType, requirements, complexity) {
        const mustCount = requirements.filter((req) => req.priority === 'must').length;
        return `Interview identified ${requirements.length} actionable requirements (${mustCount} must-have) for a ${projectType} project. Estimated delivery complexity is ${complexity}.`;
    }
    recommendationsFor(projectType, complexity, constraints, risks) {
        const recs = new Set();
        recs.add('Define explicit acceptance criteria for top-priority features before implementation starts.');
        recs.add('Track scope changes against the approved plan to prevent scope creep.');
        if (complexity !== 'low')
            recs.add('Run phased delivery with milestone reviews at the end of each phase.');
        if (constraints.some((c) => /security|privacy|compliance/i.test(c)))
            recs.add('Schedule an early security and compliance design review.');
        if (risks.length > 0)
            recs.add('Convert high-risk items into spike tasks in phase 1 to reduce uncertainty.');
        if (projectType === 'web_app')
            recs.add('Prioritize UX flows and observability before scaling infrastructure.');
        if (projectType === 'data_pipeline')
            recs.add('Add data quality checks and lineage tracking in the initial rollout.');
        if (projectType === 'api_service')
            recs.add('Lock API contracts early and generate typed client/server interfaces.');
        if (projectType === 'tool_utility')
            recs.add('Focus on CLI/UX ergonomics and comprehensive edge-case handling.');
        return [...recs];
    }
    buildRoadmap(projectType, requirements, complexity, risks) {
        const sorted = [...requirements].sort((a, b) => PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority));
        const discoveryTasks = this.requirementTasks(sorted.slice(0, 4), 'Phase 1: Discovery & Design', complexity, 1);
        const implementationTasks = this.requirementTasks(sorted.slice(4, 10), 'Phase 2: Implementation', complexity, 1.2);
        const hardeningTasks = this.requirementTasks(sorted.slice(10), 'Phase 3: Validation & Rollout', complexity, 0.9);
        if (risks.length > 0) {
            discoveryTasks.unshift({
                id: `task_${randomUUID()}`,
                title: 'Risk mitigation spikes',
                description: 'Create spike tasks for top identified risks and unknown dependencies.',
                priority: 'must',
                complexity,
                effortHours: Math.max(4, Math.round(risks.length * effortMultiplier(complexity))),
                dependencies: [],
                phase: 'Phase 1: Discovery & Design'
            });
        }
        return [
            {
                id: `phase_${randomUUID()}`,
                title: 'Phase 1: Discovery & Design',
                objective: `Validate scope, architecture, and constraints for ${projectType}.`,
                tasks: discoveryTasks,
                risks: risks.slice(0, 5)
            },
            {
                id: `phase_${randomUUID()}`,
                title: 'Phase 2: Implementation',
                objective: 'Implement prioritized capabilities with iterative checkpoints.',
                tasks: implementationTasks,
                risks: []
            },
            {
                id: `phase_${randomUUID()}`,
                title: 'Phase 3: Validation & Rollout',
                objective: 'Stabilize, validate, and release with observability and documentation.',
                tasks: hardeningTasks,
                risks: []
            }
        ];
    }
    requirementTasks(requirements, phase, complexity, multiplier) {
        return requirements.map((requirement) => ({
            id: `task_${randomUUID()}`,
            title: requirement.title,
            description: requirement.description,
            priority: requirement.priority,
            complexity,
            effortHours: Math.max(2, Math.round(effortMultiplier(complexity) * multiplier * (requirement.priority === 'must' ? 2 : 1))),
            dependencies: [],
            phase
        }));
    }
    inferAcceptanceCriteria(text) {
        const criteria = [];
        if (/api|endpoint/i.test(text))
            criteria.push('API contract is documented and validated with tests.');
        if (/dashboard|ui|screen|frontend/i.test(text))
            criteria.push('UI flow is testable and matches required behavior.');
        if (/data|pipeline|etl/i.test(text))
            criteria.push('Data is validated with quality checks and retry behavior.');
        if (criteria.length === 0)
            criteria.push('Requirement is implemented and validated by automated tests.');
        return criteria;
    }
}
//# sourceMappingURL=plan-generator.js.map