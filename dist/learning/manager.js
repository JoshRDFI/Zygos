import { ToolCreationEngine } from './creation.js';
import { ToolModificationSystem } from './modification.js';
import { SQLiteLearningStore, diffToolVersions } from './versioning.js';
export class LearningManager {
    deps;
    store;
    modifier;
    creator;
    cycleLock = Promise.resolve();
    constructor(deps) {
        this.deps = deps;
        this.store = new SQLiteLearningStore({ dbPath: deps.dbPath });
        this.modifier = new ToolModificationSystem(deps.runtime, {
            minObservationsForProposal: deps.config.minObservationsForProposal,
            minSuccessRateGain: deps.config.minSuccessRateGain,
            maxLatencyRegressionRatio: deps.config.maxLatencyRegressionRatio,
            abTestSampleSize: deps.config.abTestSampleSize,
            maxResourceCostPerTestMs: deps.config.maxResourceCostPerTestMs
        });
        this.creator = new ToolCreationEngine(deps.runtime, {
            minPatternFrequency: deps.config.minObservationsForProposal,
            maxToolCreationsPerDay: deps.config.maxToolCreationsPerDay
        });
    }
    async init() {
        await this.store.init();
        const state = await this.store.readState();
        if (!state.enabled) {
            await this.store.writeState({ ...state, enabled: this.deps.config.enabled, approvalMode: this.deps.config.approvalMode });
        }
        for (const tool of this.deps.runtime.listTools()) {
            const history = await this.store.listVersions(tool.meta.name);
            if (history.length === 0) {
                await this.store.saveVersion({
                    toolName: tool.meta.name,
                    version: tool.meta.version,
                    branch: 'main',
                    reason: 'initial_tool_registration',
                    actor: 'system',
                    changeType: 'register',
                    definition: tool,
                    isStable: true,
                    tags: ['baseline'],
                    createdAt: Date.now()
                });
            }
        }
    }
    async observeToolExecution(input) {
        if (!this.deps.config.enabled) {
            return;
        }
        await this.store.recordObservation({
            sessionId: input.sessionId,
            turnId: input.turnId,
            toolCall: input.call,
            result: input.result,
            contextTags: input.contextTags,
            contextSnapshot: input.contextSnapshot,
            createdAt: Date.now()
        });
        await this.store.appendAudit({
            action: 'observe',
            entityType: 'tool',
            entityId: input.call.name,
            details: { ok: input.result.ok, durationMs: input.result.durationMs },
            createdAt: Date.now()
        });
    }
    async runCycle(actor = 'learning_manager') {
        if (!this.deps.config.enabled) {
            return { proposals: [], applied: [] };
        }
        let proposals = [];
        let applied = [];
        this.cycleLock = this.cycleLock.then(async () => {
            const observations = await this.store.getRecentObservations(this.deps.config.observeWindowSize);
            const metrics = this.modifier.analyzeToolPerformance(observations);
            const modificationProposals = this.modifier
                .createImprovementProposals(metrics, observations)
                .slice(0, this.deps.config.maxProposalsPerCycle);
            const creationSpecs = this.creator.detectOpportunities(observations).slice(0, this.deps.config.maxProposalsPerCycle);
            const creationProposals = creationSpecs.map((spec) => this.creator.buildProposal(spec));
            proposals = [...modificationProposals, ...creationProposals].slice(0, this.deps.config.maxProposalsPerCycle);
            for (const proposal of proposals) {
                await this.store.saveProposal(proposal);
                await this.store.appendAudit({
                    action: 'proposal_created',
                    entityType: 'proposal',
                    entityId: proposal.id,
                    details: { kind: proposal.kind, risk: proposal.risk },
                    createdAt: Date.now()
                });
            }
            if (this.deps.config.autoApplyLowRisk) {
                for (const proposal of proposals.filter((p) => p.risk === 'low')) {
                    try {
                        await this.applyProposal(proposal.id, actor);
                        applied.push(proposal.id);
                    }
                    catch (error) {
                        await this.store.appendAudit({
                            action: 'safety_blocked',
                            entityType: 'proposal',
                            entityId: proposal.id,
                            details: { message: error instanceof Error ? error.message : String(error) },
                            createdAt: Date.now()
                        });
                    }
                }
            }
            const state = await this.store.readState();
            const nextMetrics = {
                ...state.metrics,
                observedExecutions: state.metrics.observedExecutions + observations.length,
                proposalsCreated: state.metrics.proposalsCreated + proposals.length,
                proposalsApplied: state.metrics.proposalsApplied + applied.length
            };
            await this.store.writeState({ ...state, metrics: nextMetrics, lastCycleAt: Date.now() });
        });
        await this.cycleLock;
        return { proposals, applied };
    }
    async listProposals(status) {
        return this.store.listProposals(status);
    }
    async applyProposal(proposalId, approver = 'system') {
        const proposals = await this.store.listProposals();
        const proposal = proposals.find((item) => item.id === proposalId);
        if (!proposal) {
            throw new Error(`Unknown proposal: ${proposalId}`);
        }
        if (proposal.status === 'applied') {
            return;
        }
        await this.store.updateProposalStatus(proposalId, 'approved', approver);
        await this.store.appendAudit({
            action: 'proposal_approved',
            entityType: 'proposal',
            entityId: proposalId,
            details: { approver },
            createdAt: Date.now()
        });
        if (proposal.kind === 'modification') {
            const payload = proposal.payload;
            if (payload.type !== 'modification') {
                throw new Error('Invalid modification payload');
            }
            const baseline = this.deps.runtime.getTool(payload.toolName);
            if (!baseline) {
                throw new Error(`Target tool not found: ${payload.toolName}`);
            }
            const latestVersions = await this.store.listVersions(payload.toolName);
            const baselineVersion = latestVersions[0];
            if (baselineVersion) {
                payload.baselineVersionId = baselineVersion.id;
            }
            const abResult = await this.modifier.runABTest(payload);
            await this.store.saveABTest(abResult);
            await this.store.appendAudit({
                action: 'ab_test_completed',
                entityType: 'tool',
                entityId: payload.toolName,
                details: abResult,
                createdAt: Date.now()
            });
            if (!this.modifier.shouldApply(abResult)) {
                await this.store.updateProposalStatus(proposalId, 'rejected', approver);
                return;
            }
            this.deps.runtime.updateTool(payload.toolName, payload.candidateDefinition);
            const saved = await this.store.saveVersion({
                toolName: payload.toolName,
                version: bumpPatchVersion(baseline.meta.version),
                branch: 'main',
                reason: payload.explanation,
                actor: approver,
                changeType: 'modify',
                definition: payload.candidateDefinition,
                parentVersionId: baselineVersion?.id,
                isStable: true,
                tags: ['learning', 'phase6'],
                createdAt: Date.now()
            });
            if (baselineVersion) {
                const afterVersion = { ...saved };
                const diff = diffToolVersions(baselineVersion, afterVersion);
                await this.store.appendAudit({
                    action: 'proposal_applied',
                    entityType: 'version',
                    entityId: String(saved.id),
                    details: { toolName: payload.toolName, changedPaths: diff.map((entry) => entry.path) },
                    createdAt: Date.now()
                });
            }
        }
        if (proposal.kind === 'creation') {
            const payload = proposal.payload;
            if (payload.type !== 'creation') {
                throw new Error('Invalid creation payload');
            }
            this.creator.applyProposal(payload);
            const saved = await this.store.saveVersion({
                toolName: payload.spec.name,
                version: payload.generatedDefinition.meta.version,
                branch: 'main',
                reason: payload.explanation,
                actor: approver,
                changeType: 'create',
                definition: payload.generatedDefinition,
                isStable: true,
                tags: ['learning', 'generated'],
                createdAt: Date.now()
            });
            await this.store.appendAudit({
                action: 'proposal_applied',
                entityType: 'version',
                entityId: String(saved.id),
                details: { toolName: payload.spec.name },
                createdAt: Date.now()
            });
        }
        await this.store.updateProposalStatus(proposalId, 'applied', approver);
    }
    async rollbackTool(toolName, targetVersionId, actor = 'system') {
        const versions = await this.store.listVersions(toolName);
        if (versions.length === 0) {
            throw new Error(`No version history for tool: ${toolName}`);
        }
        const target = targetVersionId ? versions.find((version) => version.id === targetVersionId) : versions[1];
        if (!target) {
            throw new Error(`Rollback target not found for tool '${toolName}'`);
        }
        this.deps.runtime.updateTool(toolName, target.definition);
        await this.store.saveVersion({
            toolName,
            version: target.version,
            branch: 'main',
            reason: `rollback to version id ${target.id}`,
            actor,
            changeType: 'rollback',
            definition: target.definition,
            parentVersionId: versions[0]?.id,
            isStable: true,
            tags: ['rollback'],
            createdAt: Date.now()
        });
        const state = await this.store.readState();
        await this.store.writeState({ ...state, metrics: { ...state.metrics, rollbacks: state.metrics.rollbacks + 1 } });
        await this.store.appendAudit({
            action: 'rollback',
            entityType: 'tool',
            entityId: toolName,
            details: { targetVersionId: target.id },
            createdAt: Date.now()
        });
    }
    async getMetrics() {
        return (await this.store.readState()).metrics;
    }
    async close() {
        await this.store.close();
    }
}
function bumpPatchVersion(version) {
    const parts = version.split('.').map((part) => Number(part));
    if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) {
        return '1.0.1';
    }
    return `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
}
//# sourceMappingURL=manager.js.map