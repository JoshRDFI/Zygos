export class TokenBudgetSystem {
    history = new Map();
    plan(options) {
        const hardLimitTokens = options.maxContextTokens;
        const reservedOutputTokens = options.reserveOutputTokens ?? Math.round(hardLimitTokens * 0.22);
        const reservedToolTokens = options.reserveToolTokens ?? Math.round(hardLimitTokens * 0.1);
        const available = Math.max(0, hardLimitTokens - reservedOutputTokens - reservedToolTokens);
        const strategy = options.strategy ?? 'priority_based';
        const allocation = this.allocate(available, strategy);
        return {
            strategy,
            hardLimitTokens,
            reservedOutputTokens,
            reservedToolTokens,
            availableForHistoryTokens: allocation.historyTokens,
            availableForRetrievalTokens: allocation.retrievalTokens,
            availableForInputTokens: allocation.inputTokens
        };
    }
    buildWindow(model, plan, usedTokens, thresholdRatio = 0.82) {
        return {
            model,
            maxTokens: plan.hardLimitTokens,
            reservedOutputTokens: plan.reservedOutputTokens,
            reservedToolTokens: plan.reservedToolTokens,
            usedTokens,
            remainingTokens: Math.max(0, plan.hardLimitTokens - usedTokens),
            thresholdRatio
        };
    }
    trackTurn(sessionId, usage) {
        const bucket = this.history.get(sessionId) ?? [];
        bucket.push(usage);
        if (bucket.length > 200) {
            bucket.shift();
        }
        this.history.set(sessionId, bucket);
    }
    estimateTurns(turns) {
        return turns.reduce((sum, turn) => sum + this.estimateTurnTokens(turn), 0);
    }
    estimateTurnTokens(turn) {
        if (turn.tokenUsage?.totalTokens !== undefined) {
            return turn.tokenUsage.totalTokens;
        }
        const speakerPenalty = turn.speaker === 'tool' ? 8 : turn.speaker === 'summary' ? 4 : 2;
        return Math.max(1, Math.ceil(turn.content.length / 4) + speakerPenalty);
    }
    predictNextTurn(sessionId) {
        const usages = this.history.get(sessionId) ?? [];
        if (usages.length === 0) {
            return 250;
        }
        const weights = usages.slice(-10).map((_, index, arr) => index + 1 + arr.length * 0.1);
        const weightedTotal = usages.slice(-10).reduce((sum, usage, index) => sum + usage.totalTokens * weights[index], 0);
        const weightSum = weights.reduce((sum, w) => sum + w, 0);
        return Math.max(64, Math.round(weightedTotal / weightSum));
    }
    enforceHardLimit(currentTokens, plan) {
        if (currentTokens <= plan.hardLimitTokens) {
            return { allowed: true };
        }
        return {
            allowed: false,
            reason: `Context tokens ${currentTokens} exceed hard limit ${plan.hardLimitTokens}`
        };
    }
    createReport(sessionId, turns, window) {
        const bySpeaker = turns.reduce((acc, turn) => {
            acc[turn.speaker] += this.estimateTurnTokens(turn);
            return acc;
        }, { system: 0, user: 0, assistant: 0, tool: 0, summary: 0 });
        const usedInputTokens = turns.reduce((sum, turn) => {
            if (turn.speaker === 'assistant' || turn.speaker === 'tool') {
                return sum;
            }
            return sum + this.estimateTurnTokens(turn);
        }, 0);
        const usedOutputTokens = turns.reduce((sum, turn) => {
            if (turn.speaker === 'assistant' || turn.speaker === 'tool' || turn.speaker === 'summary') {
                return sum + this.estimateTurnTokens(turn);
            }
            return sum;
        }, 0);
        const projectedNextTurnTokens = this.predictNextTurn(sessionId);
        const risk = window.remainingTokens <= projectedNextTurnTokens
            ? 'high'
            : window.remainingTokens <= projectedNextTurnTokens * 2
                ? 'medium'
                : 'low';
        return {
            sessionId,
            generatedAt: Date.now(),
            usedInputTokens,
            usedOutputTokens,
            projectedNextTurnTokens,
            remainingTokens: window.remainingTokens,
            overflowRisk: risk,
            bySpeaker
        };
    }
    allocate(available, strategy) {
        if (strategy === 'equal') {
            const each = Math.floor(available / 3);
            return {
                inputTokens: each,
                retrievalTokens: each,
                historyTokens: available - each * 2
            };
        }
        return {
            inputTokens: Math.round(available * 0.18),
            retrievalTokens: Math.round(available * 0.22),
            historyTokens: Math.max(0, available - Math.round(available * 0.18) - Math.round(available * 0.22))
        };
    }
}
//# sourceMappingURL=budget.js.map