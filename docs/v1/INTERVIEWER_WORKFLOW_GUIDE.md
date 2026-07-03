# Interactive Interviewer Workflow Guide (Phase 7)

## Overview

The interviewer workflow adds requirement discovery and build planning before execution for complex requests.

Core modules:
- `src/interviewer/interviewer.ts`
- `src/interviewer/plan-generator.ts`
- `src/types/interviewer.types.ts`

## CLI usage

### 1) Start interview

```bash
npm run dev -- --interview --interview-action start --session my_project "Build a SaaS admin dashboard"
```

### 2) Continue interview (answer)

```bash
npm run dev -- --interview --interview-action answer --session my_project --stakeholder pm "Must support SSO, RBAC, and audit logs"
```

### 3) Check interview status

```bash
npm run dev -- --interview --interview-action status --session my_project "status"
```

### 4) Complete interview + generate plan

```bash
npm run dev -- --interview --interview-action complete --session my_project "complete"
```

### 5) Export generated plan

```bash
npm run dev -- --interview --interview-action plan_export --session my_project "export"
```

## Gating behavior

When interview gating is enabled (`config.interview.requireForComplexBuilds: true`), complex standard requests are redirected to interview mode unless override is provided.

Override example:

```bash
npm run dev -- "Build a multi-tenant compliance platform" --interview-override
```

## Templates

Built-in templates:
- `web_app`
- `data_pipeline`
- `api_service`
- `tool_utility`
- `general`

Config control:
- `interview.template: auto` (default inference)
- or force specific template (e.g., `interview.template: api_service`)

## Plan outputs

Generated plans include:
- extracted requirements
- constraints and assumptions
- risk list
- complexity + effort estimate
- phase-based implementation roadmap
- task breakdown

Export formats:
- JSON (`BuildPlan` object)
- Markdown (`BuildPlanExport.markdown`)

## Example interview flow

1. User asks for a complex project.
2. Engine emits `interview_progress` with first question.
3. User answers multiple turns.
4. Interview completes automatically or via explicit `complete` action.
5. Engine emits `interview_plan_generated` and stores versioned plan.
6. Plan can be exported and used as implementation roadmap.
