# Buno AI — Master Plan

> Status: discovery and foundation
> Owner: Buno
> Strategy: one intelligence layer orchestrating a portfolio of independently deployable products.

## Product vision

Buno AI is the central intelligence and execution interface for the Buno venture-building ecosystem. It must understand a user's goal, build a plan, select authorized product capabilities, execute through typed integrations, report evidence and outcomes, and request approval before sensitive or irreversible actions.

The platform is not a collection of chatbot shortcuts. Each product remains an independently deployable service with a documented API contract. Buno AI coordinates them through a capability registry and governed execution layer.

## Repository discovery — 2026-11-06

The connected GitHub account exposes the following relevant repositories:

| Product / component | Repository | Current evidence | Initial status |
|---|---|---|---|
| Buno AI platform | `JoaoBuosi/Buno` | React + TypeScript + Vite frontend; FastAPI backend; SQLAlchemy/Alembic; auth, chat streaming, projects, documents, memories, agents, governance and venture endpoints | Existing foundation; requires runtime validation |
| Aegis Agent Gateway | `JoaoBuosi/aegis-agent-gateway` | Spring Boot REST gateway; README says runtime payload/response mapping is generic and must be aligned to actual Aegis Runtime10 contract | Prototype / contract unverified |
| Buno Flow Commerce | `JoaoBuosi/buno-flow-commerce` | Spring Boot order API, PostgreSQL and Kafka consumer; README documents no durable transactional outbox | Prototype |
| Buno Knowledge Engine | `JoaoBuosi/buno-knowledge-engine` | Spring Boot document API and textual retrieval; README explicitly says no embeddings/vector search and runtime contract needs alignment | Prototype |
| Buno InfraPilot | `JoaoBuosi/buno-infrapilot` | Spring Boot infrastructure request/approval workflow; README says no Terraform execution and in-memory storage | Prototype |
| Buno Ops Sentinel | `JoaoBuosi/buno-ops-sentinel` | Spring Boot event ingestion and assisted analysis; README says in-memory events and recommendation-only behavior | Prototype |

Five of the ten product identities are confirmed in the available repositories. Products 06–10 are intentionally marked **unidentified** until their exact names and repositories are confirmed. Do not invent product names or claim integrations that do not exist.

Additional repository observations:
- `JoaoBuosi/Buno-Frontend` currently appears empty.
- `JoaoBuosi/Buno-api` contains a `buni-api` directory and needs separate inspection before deciding whether it is active or superseded by the API inside `JoaoBuosi/Buno`.
- The Buno platform's current LLM provider implementation talks directly to Ollama. Provider abstraction and model interchangeability need an explicit design and tests.
- The chat flow already includes streaming, conversation history, optional web search, document context, memory retrieval and call metering. Tool execution through a governed product registry is the next major capability to design.

## Target architecture

1. **Experience layer** — React/TypeScript web app, chat, projects, agent runs, product catalog, execution timeline and admin/usage views.
2. **Buno AI Core** — intent understanding, task decomposition, planning, context assembly, model routing and response synthesis.
3. **Agent runtime** — bounded agent loop with typed tool calls, timeouts, retries, budgets, cancellation and trace IDs.
4. **Capability registry** — machine-readable descriptions of each product's tools, input/output schemas, health, auth requirements, risk level and version.
5. **Integration adapters** — one adapter per product; typed HTTP clients, authentication, contract validation, idempotency and normalized errors.
6. **Governance plane** — deny-by-default permissions, least privilege, approval workflow, policy checks, audit events and evidence.
7. **Data plane** — PostgreSQL as source of truth; pgvector only where semantic retrieval is implemented and evaluated; Redis for cache/queues only where justified.
8. **Observability** — structured logs, traces, metrics, per-run cost/latency, tool outcomes and audit trail.

## Non-negotiable execution rules

- No arbitrary shell, SQL, Terraform, payment, messaging or external side effects directly from model-generated text.
- Models propose typed actions; deterministic application code validates schemas, identity, authorization, risk and policy before execution.
- Sensitive, destructive, financial, infrastructure-changing or externally visible actions require explicit approval.
- Every tool call has a trace ID, actor, tenant/user scope, input validation, timeout, result, status and audit record.
- Secrets are never committed to Git or returned in prompts/logs.
- Product integrations must fail closed when auth, policy, contract validation or approval is unavailable.
- The model is not the source of truth for product state; read state from product APIs.
- Do not mark a product as integrated until contract tests and an end-to-end test pass against a running service.

## Delivery sequence

### Phase 0 — Discovery and baseline
- Confirm all ten product names and repositories.
- Inspect each README, source tree, dependencies, environment variables, API routes, persistence, tests and deployment files.
- Run existing tests/builds where execution access is available.
- Produce a product-by-product gap matrix and dependency map.
- Preserve current branches; work in feature branches and use pull requests.

### Phase 1 — Buno AI core hardening
- Define provider interface and adapters; keep Ollama as one provider, not the only provider.
- Add model capability metadata, timeouts, retries, fallback policy and usage/cost accounting.
- Establish prompt/context boundaries and untrusted-content handling.
- Add evaluation datasets for correctness, tool selection, refusal, latency and cost.
- Add tests for provider failures, empty/truncated output, cancellation and streaming.

### Phase 2 — Governed tool execution
- Define versioned tool manifest and JSON schemas.
- Build registry, planner/executor boundary, policy engine and approval state machine.
- Add execution records, idempotency keys, audit trail and per-run budgets.
- Start with read-only, low-risk capabilities before write operations.

### Phase 3 — Product integrations
- Integrate each product through a typed adapter and health check.
- Add contract tests and mocked failure scenarios.
- Prioritize a demonstrable vertical slice across multiple products, then expand to all ten.
- Keep each service independently deployable and observable.

### Phase 4 — User experience and commercialization
- Product catalog and connection status.
- Plan, execute, approve and inspect a workflow in the UI.
- Meter credits by model tokens and product/tool usage.
- Enforce quotas, rate limits, tenant isolation and abuse controls.
- Add onboarding, documentation and a safe demo workspace.

## Definition of done for an integration

A product is considered integrated only when:
1. Its purpose and supported capabilities are documented.
2. Its API contract and authentication are explicit and versioned.
3. The adapter validates all inputs and outputs.
4. Authorization and risk policy are enforced outside the model.
5. Timeouts, retries, idempotency and normalized errors are implemented where applicable.
6. Unit and contract tests pass.
7. A live end-to-end test demonstrates a real outcome.
8. Logs, metrics, trace ID and audit evidence can be inspected.
9. Failure and rollback/recovery behavior are documented.

## Immediate next actions

1. Finish discovery of the remaining five products and inspect `Buno-api`.
2. Inspect the Buno platform's agent, governance, configuration and test modules in detail.
3. Establish baseline test/build results before modifying runtime behavior.
4. Design the capability manifest and integration contract.
5. Implement the first vertical slice with one read-only capability, then one approval-gated action.

## Accuracy note

This document records repository contents and README claims observed during initial discovery. It does not claim that services have been built, deployed, tested, secured or integrated. Those states must be earned through reproducible validation.
