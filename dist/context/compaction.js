import { randomUUID } from 'node:crypto';
import { TokenBudgetSystem } from './budget.js';
export class HeuristicSummaryGenerator {
    async summarize(input) {
        const keyLines = input.turns
            .slice(0, 16)
            .map((turn) => `${turn.speaker}: ${normalize(turn.content, 180)}`)
            .join('\n');
        const facts = extractKeyFacts(input.turns).slice(0, 8);
        const tools = input.turns.filter((turn) => turn.contentType === 'tool_result').slice(0, 6);
        const lines = ['Conversation summary:'];
        if (facts.length > 0) {
            lines.push('Facts:');
            lines.push(...facts.map((fact) => `- ${fact}`));
        }
        if (tools.length > 0 && input.strategy.preserveToolPairs) {
            lines.push('Tool outcomes:');
            lines.push(...tools.map((tool) => `- ${tool.toolName ?? 'tool'} => ${normalize(tool.content, 120)}`));
        }
        lines.push('Details:');
        lines.push(keyLines);
        return lines.join('\n');
    }
}
export class ContextCompactor {
    budget;
    summarizer;
    constructor(budget, summarizer = new HeuristicSummaryGenerator()) {
        this.budget = budget;
        this.summarizer = summarizer;
    }
    async compact(input) {
        const currentTokens = this.budget.estimateTurns(input.turns);
        if (currentTokens <= input.maxTokens) {
            return {
                compacted: false,
                removedTurnIds: [],
                preservedTurnIds: input.turns.map((turn) => turn.id),
                tokenDelta: 0
            };
        }
        const sorted = [...input.turns].sort((a, b) => a.turnIndex - b.turnIndex);
        const preserveRecent = Math.max(1, input.strategy.preserveRecentTurns);
        const protectedRecent = new Set(sorted.slice(-preserveRecent).map((turn) => turn.id));
        const protectedTagged = new Set(sorted.filter((turn) => input.strategy.preserveTaggedTurns && turn.tags.length > 0).map((turn) => turn.id));
        const candidateTurns = sorted.filter((turn) => {
            if (protectedRecent.has(turn.id)) {
                return false;
            }
            if (protectedTagged.has(turn.id)) {
                return false;
            }
            if (turn.contentType === 'tool_result' && input.strategy.preserveToolPairs) {
                return false;
            }
            return true;
        });
        if (candidateTurns.length < 2) {
            return {
                compacted: false,
                removedTurnIds: [],
                preservedTurnIds: sorted.map((turn) => turn.id),
                tokenDelta: 0,
                warning: 'No safe compaction candidates found.'
            };
        }
        const targetTokens = Math.max(64, Math.floor(input.maxTokens * input.strategy.targetReductionRatio));
        const toSummarize = [];
        let running = currentTokens;
        for (const turn of candidateTurns) {
            toSummarize.push(turn);
            running -= this.budget.estimateTurnTokens(turn);
            if (running <= targetTokens) {
                break;
            }
        }
        const summaryText = await this.summarizer.summarize({
            sessionId: input.sessionId,
            turns: toSummarize,
            strategy: input.strategy,
            targetTokens
        });
        const maxLen = input.strategy.maxSummaryTokens * 4;
        const summaryTurn = {
            id: `summary_${randomUUID()}`,
            sessionId: input.sessionId,
            turnIndex: toSummarize[toSummarize.length - 1]?.turnIndex ?? sorted[0]?.turnIndex ?? 0,
            speaker: 'summary',
            contentType: 'summary',
            content: normalize(summaryText, maxLen),
            createdAt: Date.now(),
            updatedAt: Date.now(),
            importanceScore: 0.8,
            tags: ['summary', 'compacted'],
            summaryOfTurnIds: toSummarize.map((turn) => turn.id),
            isCompacted: false,
            piiDetected: false
        };
        const removedTurnIds = toSummarize.map((turn) => turn.id);
        return {
            compacted: true,
            summaryTurn,
            removedTurnIds,
            preservedTurnIds: sorted.filter((turn) => !removedTurnIds.includes(turn.id)).map((turn) => turn.id),
            tokenDelta: currentTokens - (running + this.budget.estimateTurnTokens(summaryTurn))
        };
    }
}
function normalize(text, maxLen) {
    const trimmed = text.replace(/\s+/g, ' ').trim();
    if (trimmed.length <= maxLen) {
        return trimmed;
    }
    return `${trimmed.slice(0, Math.max(8, maxLen - 1))}…`;
}
function extractKeyFacts(turns) {
    const facts = [];
    const factPattern = /(my name is|i prefer|remember that|we decided|the requirement is)\s+([^.!?\n]+)/gi;
    for (const turn of turns) {
        for (const match of turn.content.matchAll(factPattern)) {
            facts.push(`${match[1]} ${match[2]}`.trim());
        }
    }
    return Array.from(new Set(facts));
}
//# sourceMappingURL=compaction.js.map