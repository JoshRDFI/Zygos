import type { QueryEngine } from '../types/core.types.js';
import type { ReasoningDepthProfile } from '../types/rdt.types.js';
/** Creates a fully wired query engine with hardened provider routing and validation. */
export declare function createEngine(configPath?: string, routeOverride?: {
    provider?: string;
    model?: string;
    rdtEnabled?: boolean;
    rdtProfile?: ReasoningDepthProfile;
}): Promise<QueryEngine>;
//# sourceMappingURL=bootstrap.d.ts.map