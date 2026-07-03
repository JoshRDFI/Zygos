# Self-Learning System Guide (Phase 6)

Phase 6 adds recursive self-improvement to Zygos. The learning subsystem is enabled by default and continuously observes runtime tool execution to propose and apply safe improvements.

## What gets added

- `src/learning/manager.ts`
  - Orchestrates observation, proposal generation, approval/apply flow, A/B test gating, and rollback.
- `src/learning/modification.ts`
  - Computes tool performance metrics from observations and generates modification proposals.
  - Runs side-by-side A/B validation and regression checks before applying updates.
- `src/learning/creation.ts`
  - Detects repeated unresolved patterns and generates template-based runtime tools.
  - Enforces safety validation (allowlisted templates, safe naming, suspicious pattern checks).
- `src/learning/versioning.ts`
  - SQLite-backed persistence for observations, proposals, tool versions, A/B tests, audit trail, and manager state.
- `src/types/learning.types.ts`
  - Complete type contracts for learning state, proposals, version records, metrics, and persistence APIs.

## Runtime flow

1. QueryEngine executes tools.
2. Each tool call/result pair is recorded by `LearningManager.observeToolExecution`.
3. `LearningManager.runCycle` analyzes recent observations and creates:
   - modification proposals (for latency/failure patterns)
   - creation proposals (for repeated unresolved call patterns)
4. Low-risk proposals are auto-applied when configured (`learning.autoApplyLowRisk=true`).
5. All changes are versioned in SQLite with full audit entries.
6. Regression or weak A/B results block application; rollbacks are supported.

## Safety guardrails

- Template allowlist for generated tools (`json_transform`, `text_template`, `math_expression`).
- Proposal risk classification (`low`, `medium`, `high`).
- A/B checks for modification proposals before apply.
- Latency regression tolerance and minimum success gain thresholds.
- Full audit trail (`learning_audit`) and tool version history (`tool_versions`).

## CLI commands

- `--learning-list` → list proposals
- `--learning-apply <proposalId>` → manually apply a proposal
- `--learning-rollback <toolName[:versionId]>` → rollback to previous/specified version
- `--learning-metrics` → print learning metrics snapshot

## Configuration

`config/default.yaml` includes:

- `learning.enabled`
- `learning.approvalMode`
- `learning.autoApplyLowRisk`
- `learning.maxProposalsPerCycle`
- `learning.minObservationsForProposal`
- `learning.observeWindowSize`
- `learning.maxModificationsPerHour`
- `learning.maxToolCreationsPerDay`
- `learning.abTestSampleSize`
- `learning.maxLatencyRegressionRatio`
- `learning.minSuccessRateGain`
- `learning.maxResourceCostPerTestMs`

By default, the learning database is stored at `.zygos/learning.db` (override via `ZYGOS_LEARNING_DB`).
