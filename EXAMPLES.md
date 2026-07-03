# Usage Examples

Practical command examples for Zygos.

> Replace model names with those available in your environment.

---

## 1) Basic conversation

```bash
npm run dev -- "Write a concise README for a todo app"
```

With explicit session continuity:

```bash
npm run dev -- "We're building a CRM for SMBs" --session crm_demo
npm run dev -- "Now define API endpoints" --session crm_demo
```

---

## 2) Using different providers

## OpenAI

```bash
npm run dev -- "Draft a launch checklist" --provider openai --model gpt-4o-mini
```

## Anthropic

```bash
npm run dev -- "Create risk mitigation plan" --provider anthropic --model claude-3-5-haiku-latest
```

## Ollama

```bash
npm run dev -- "Summarize distributed tracing" --provider ollama --model llama3.1:8b
```

## vLLM

```bash
npm run dev -- "Generate test cases" --provider vllm --model mistral-7b-instruct
```

## Local deterministic custom provider

```bash
npm run dev -- "Hello world" --provider custom --model demo
```

---

## 3) Enable RDT reasoning

Balanced:

```bash
npm run dev -- "Design a data retention policy" --rdt true --rdt-profile balanced
```

Deep:

```bash
npm run dev -- "Create a migration strategy from monolith to microservices" --rdt true --rdt-profile deep
```

Shallow:

```bash
npm run dev -- "Give a quick 3-bullet summary" --rdt true --rdt-profile shallow
```

---

## 4) Using tools

The default bootstrap registers a built-in `get_time` tool. Trigger pattern in demo provider:

```bash
npm run dev -- "/time America/Los_Angeles" --provider custom --model demo
```

You should see tool events in CLI logs (`[tool:start]`, `[tool:done]`).

---

## 5) Running interviews

Start:

```bash
npm run dev -- --interview --interview-action start --session build_001 "Build a multi-tenant SaaS analytics platform"
```

Answer question(s):

```bash
npm run dev -- --interview --interview-action answer --session build_001 --stakeholder pm "Need SSO, role-based access, dashboards, exports"
npm run dev -- --interview --interview-action answer --session build_001 --stakeholder eng "Prefer Node.js + Postgres + Redis"
```

Check status:

```bash
npm run dev -- --interview --interview-action status --session build_001 "Status"
```

Complete and generate plan:

```bash
npm run dev -- --interview --interview-action complete --session build_001 "Generate implementation plan"
```

Export plan:

```bash
npm run dev -- --interview --interview-action plan_export --session build_001 "Export plan"
```

---

## 6) Learning system in action

List proposals:

```bash
npm run dev -- --learning-list
```

Apply proposal:

```bash
npm run dev -- --learning-apply <proposal_id>
```

Rollback tool changes:

```bash
npm run dev -- --learning-rollback my_tool
npm run dev -- --learning-rollback my_tool:3
```

Metrics:

```bash
npm run dev -- --learning-metrics
```

---

## 7) Search conversation history

```bash
npm run dev -- "Define auth strategy" --session hist_001
npm run dev -- "Now include RBAC and auditing" --session hist_001
npm run dev -- --history-search "RBAC" --session hist_001
```

---

## 8) Advanced workflows

## A) Product planning workflow

```bash
npm run dev -- --interview --interview-action start --session prod_plan "Build customer support AI assistant"
npm run dev -- --interview --interview-action complete --session prod_plan "Finalize and plan"
npm run dev -- "Turn the plan into a 2-sprint backlog" --session prod_plan --rdt true --rdt-profile deep
```

## B) Provider fallback testing

Use a custom config where primary is intentionally unreachable and fallback is valid; then run:

```bash
npm run dev -- "Check fallback behavior" --config config/providers.example.yaml
```

## C) Strict reproducible local run

```bash
npm run dev -- "Produce deterministic answer" --provider custom --model demo --rdt false
```

---

## More references

- Fast setup: [QUICKSTART.md](./QUICKSTART.md)
- Full config: [CONFIGURATION.md](./CONFIGURATION.md)
- Overview: [README.md](./README.md)
