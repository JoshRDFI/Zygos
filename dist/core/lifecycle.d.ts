import type { QueryState } from '../types/core.types.js';
export declare function canTransition(from: QueryState, to: QueryState): boolean;
export declare function assertTransition(from: QueryState, to: QueryState): void;
export declare function nextStateAfterModel(hasPendingTools: boolean): QueryState;
//# sourceMappingURL=lifecycle.d.ts.map