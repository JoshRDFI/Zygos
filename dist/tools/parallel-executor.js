function topoLevels(nodes) {
    const map = new Map(nodes.map((node) => [node.call.id, node]));
    const indegree = new Map(nodes.map((node) => [node.call.id, 0]));
    const adjacency = new Map();
    for (const node of nodes) {
        for (const dep of node.dependencies) {
            if (!map.has(dep))
                continue;
            indegree.set(node.call.id, (indegree.get(node.call.id) ?? 0) + 1);
            const links = adjacency.get(dep) ?? [];
            links.push(node.call.id);
            adjacency.set(dep, links);
        }
    }
    const queue = nodes.filter((node) => (indegree.get(node.call.id) ?? 0) === 0);
    const levels = [];
    while (queue.length > 0) {
        const level = [];
        const width = queue.length;
        for (let i = 0; i < width; i += 1) {
            const node = queue.shift();
            if (!node)
                continue;
            level.push(node);
            for (const next of adjacency.get(node.call.id) ?? []) {
                indegree.set(next, (indegree.get(next) ?? 0) - 1);
                if ((indegree.get(next) ?? 0) === 0) {
                    const n = map.get(next);
                    if (n)
                        queue.push(n);
                }
            }
        }
        levels.push(level);
    }
    // Cycle fallback: append remaining nodes as serial levels.
    const processed = new Set(levels.flat().map((node) => node.call.id));
    for (const node of nodes) {
        if (!processed.has(node.call.id)) {
            levels.push([node]);
        }
    }
    return levels;
}
export class ParallelExecutionOrchestrator {
    options;
    constructor(options = { concurrency: 4 }) {
        this.options = options;
    }
    async execute(nodes, ctx, runOne) {
        const levels = topoLevels(nodes);
        const results = [];
        const failures = [];
        for (const level of levels) {
            const serial = level.filter((node) => !node.parallelSafe);
            const parallel = level.filter((node) => node.parallelSafe);
            for (const node of serial) {
                const result = await runOne(node.call, ctx);
                results.push(result);
                if (!result.ok)
                    failures.push(result);
            }
            const resourceLocks = new Set();
            const queue = [...parallel];
            const inflight = new Set();
            const maxConcurrency = Math.max(1, this.options.concurrency);
            const scheduleNext = () => {
                while (inflight.size < maxConcurrency && queue.length > 0) {
                    const nextIndex = queue.findIndex((candidate) => !resourceLocks.has(candidate.resourceKey));
                    if (nextIndex < 0) {
                        break;
                    }
                    const node = queue.splice(nextIndex, 1)[0];
                    resourceLocks.add(node.resourceKey);
                    const p = runOne(node.call, ctx)
                        .then((result) => {
                        results.push(result);
                        if (!result.ok) {
                            failures.push(result);
                        }
                    })
                        .finally(() => {
                        resourceLocks.delete(node.resourceKey);
                        inflight.delete(p);
                    });
                    inflight.add(p);
                }
            };
            scheduleNext();
            while (inflight.size > 0 || queue.length > 0) {
                if (inflight.size === 0) {
                    // deadlock guard for contention: force one queue item serially.
                    const forced = queue.shift();
                    if (forced) {
                        const result = await runOne(forced.call, ctx);
                        results.push(result);
                        if (!result.ok)
                            failures.push(result);
                    }
                    scheduleNext();
                    continue;
                }
                await Promise.race(inflight);
                scheduleNext();
            }
        }
        return { results, failures };
    }
}
//# sourceMappingURL=parallel-executor.js.map