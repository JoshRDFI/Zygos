const transitionMap = {
    IDLE: ['PREPARE_CONTEXT'],
    PREPARE_CONTEXT: ['PLAN_PROVIDER', 'FAILED_TERMINAL'],
    PLAN_PROVIDER: ['MODEL_STREAMING', 'FAILED_TERMINAL'],
    MODEL_STREAMING: ['TOOL_CALLS_PENDING', 'RDT_OPTIONAL', 'FINALIZE', 'FAILED_TERMINAL'],
    TOOL_CALLS_PENDING: ['TOOL_EXECUTING', 'MODEL_STREAMING', 'FAILED_TERMINAL'],
    TOOL_EXECUTING: ['MODEL_STREAMING', 'FINALIZE', 'FAILED_TERMINAL'],
    RDT_OPTIONAL: ['FINALIZE', 'FAILED_TERMINAL'],
    FINALIZE: ['PERSIST', 'FAILED_TERMINAL'],
    PERSIST: ['IDLE', 'FAILED_TERMINAL'],
    FAILED_TERMINAL: ['IDLE']
};
export function canTransition(from, to) {
    return transitionMap[from].includes(to);
}
export function assertTransition(from, to) {
    if (!canTransition(from, to)) {
        throw new Error(`Invalid state transition: ${from} -> ${to}`);
    }
}
export function nextStateAfterModel(hasPendingTools) {
    return hasPendingTools ? 'TOOL_CALLS_PENDING' : 'RDT_OPTIONAL';
}
//# sourceMappingURL=lifecycle.js.map