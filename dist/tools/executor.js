import { StreamingToolExecutor } from './streaming-executor.js';
/**
 * Backward-compatible executor facade.
 * Phase 3 uses StreamingToolExecutor under the hood while preserving execute/executeBatch signatures.
 */
export class ToolExecutor {
    delegate;
    constructor(registry, options = {}) {
        this.delegate = new StreamingToolExecutor(registry, options);
    }
    async execute(call, ctx) {
        return this.delegate.execute(call, ctx);
    }
    async executeBatch(calls, ctx) {
        return this.delegate.executeBatch(calls, ctx);
    }
    executeBatchStream(calls, ctx) {
        return this.delegate.executeBatchStream(calls, ctx);
    }
    getMetrics() {
        return this.delegate.getMetrics();
    }
}
//# sourceMappingURL=executor.js.map