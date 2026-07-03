import type { QueryState } from '../types/core.types.js';

const transitionMap: Record<QueryState, QueryState[]> = {
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

export function canTransition(from: QueryState, to: QueryState): boolean {
  return transitionMap[from].includes(to);
}

export function assertTransition(from: QueryState, to: QueryState): void {
  if (!canTransition(from, to)) {
    throw new Error(`Invalid state transition: ${from} -> ${to}`);
  }
}

export function nextStateAfterModel(hasPendingTools: boolean): QueryState {
  return hasPendingTools ? 'TOOL_CALLS_PENDING' : 'RDT_OPTIONAL';
}
