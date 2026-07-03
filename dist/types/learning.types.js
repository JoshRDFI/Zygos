import { z } from 'zod';
export const learningProposalKindSchema = z.enum(['modification', 'creation']);
export const learningProposalStatusSchema = z.enum(['proposed', 'approved', 'rejected', 'applied', 'rolled_back']);
export const learningRiskSchema = z.enum(['low', 'medium', 'high']);
export const learningApprovalModeSchema = z.enum(['auto', 'manual', 'optional_human']);
//# sourceMappingURL=learning.types.js.map