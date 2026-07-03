export const RDT_PROFILES = {
    shallow: {
        recurrent: {
            enabled: true,
            temperature: 0.15,
            minLoopIters: 1,
            maxLoopIters: 2,
            allowBacktracking: false,
            allowParallelPaths: false,
            systemInstruction: 'Perform concise iterative reasoning.'
        },
        loop: { maxLoopIters: 2, minLoopIters: 1, maxRevisionDepth: 1 },
        confidence: {
            thresholds: { earlyExit: 0.78, revise: 0.52, floor: 0.2 },
            adaptive: true,
            adaptUpDelta: 0.02,
            adaptDownDelta: 0.04,
            smoothingFactor: 0.6
        }
    },
    balanced: {
        recurrent: {
            enabled: true,
            temperature: 0.2,
            minLoopIters: 1,
            maxLoopIters: 4,
            allowBacktracking: true,
            allowParallelPaths: true,
            systemInstruction: 'Perform iterative, evidence-grounded reasoning.'
        },
        loop: { maxLoopIters: 4, minLoopIters: 1, maxRevisionDepth: 2 },
        confidence: {
            thresholds: { earlyExit: 0.84, revise: 0.55, floor: 0.25 },
            adaptive: true,
            adaptUpDelta: 0.03,
            adaptDownDelta: 0.04,
            smoothingFactor: 0.55
        }
    },
    deep: {
        recurrent: {
            enabled: true,
            temperature: 0.22,
            minLoopIters: 2,
            maxLoopIters: 7,
            allowBacktracking: true,
            allowParallelPaths: true,
            systemInstruction: 'Perform deep multi-hop reasoning with validation and revision.'
        },
        loop: { maxLoopIters: 7, minLoopIters: 2, maxRevisionDepth: 3 },
        confidence: {
            thresholds: { earlyExit: 0.9, revise: 0.58, floor: 0.3 },
            adaptive: true,
            adaptUpDelta: 0.04,
            adaptDownDelta: 0.05,
            smoothingFactor: 0.5
        }
    }
};
//# sourceMappingURL=rdt.types.js.map