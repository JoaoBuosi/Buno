# Buno AI — Architecture Decisions

Date: 2026-11-06
Status: Accepted

## Product configuration

| Surface | Decision | Responsibility |
|---|---|---|
| Web | Existing React + TypeScript + Vite | Main browser experience |
| Terminal | Python + Textual | Interactive TUI with streaming, agents, product status, tasks, approvals and diagnostics |
| Desktop | Tauri + existing React UI | Lightweight installable desktop client |
| Backend | Existing FastAPI application | Shared API, identity, sessions, memory, orchestration and governance |
| Data | Existing PostgreSQL/SQLAlchemy/Alembic foundation | Durable conversations, users, agents, memory and execution records |
| Local model | Ollama remains supported | Local provider option, not a hard-coded platform boundary |

## Balanced delivery priority

The delivery optimizes for a working vertical slice across intelligence, product integrations and interfaces. No surface may invent its own agent runtime, memory store, permission rules or product state.

The shared backend remains the source of truth. Web, Textual and Tauri are clients of versioned HTTP/SSE APIs. Desktop wraps the existing React experience; it does not fork the frontend.

## Terminal experience

Textual is the selected TUI framework. Initial commands:

- `/help`
- `/agents`
- `/products`
- `/tasks`
- `/memory`
- `/doctor`

The TUI must consume the same authenticated API and streaming protocol as the web client. Tool execution and approvals remain server-governed; the terminal is not an unrestricted shell agent.

## Desktop experience

Tauri is selected to package the existing React frontend. The desktop app should connect to the same FastAPI backend and use the same auth/session model. Local backend bundling is a later decision, not a prerequisite for the first desktop demo.

## Shared execution contract

The target workflow is:

1. Receive a user goal.
2. Build a bounded plan and identify candidate capabilities.
3. Resolve tools from a versioned registry.
4. Validate input schemas and user permissions in deterministic code.
5. Require explicit approval for sensitive or externally visible actions.
6. Execute through product-specific adapters with timeout, trace ID and idempotency where applicable.
7. Persist status, result and evidence.
8. Return a concise synthesis to any client.

Model output is never authorization. No arbitrary shell, SQL, infrastructure, payment or messaging action may execute directly from generated text.

## Repository audit findings

- The existing FastAPI application already exposes auth, streaming chat, conversations, projects, agents, documents, memories, venture and governance routes.
- Chat already retrieves conversation history, optional web context, document chunks and memories before streaming from the configured LLM provider.
- The current LLM provider implementation is Ollama-specific. A provider interface and adapter boundary are needed before adding cloud providers or routing.
- The launcher currently sets its frontend directory to `web/`, while the inspected repository root contains `package.json`, `src/` and `vite.config.ts` at the root. Verify and correct this path mismatch before relying on `python buno.py preparar/iniciar`.
- Repository source has not been executed in this audit. Test/build status is therefore unknown, not passing.
- Product identities 06–10 remain unconfirmed; do not create placeholder product names or claim integrations.

## Implementation order

1. Reconcile repository layout and establish reproducible test/build baseline.
2. Define provider interface and model capability/usage metadata.
3. Define versioned capability manifest, registry and normalized execution result.
4. Add bounded orchestrator with policy and approval gates.
5. Integrate read-only product capabilities first, then approval-gated writes.
6. Build Textual client on the shared API/SSE contract.
7. Package the existing React client with Tauri.
8. Add end-to-end demo scenarios, failure paths and evidence views.

## Acceptance criteria

- Web, TUI and desktop share authentication, memory, execution history and policy.
- A demo request visibly plans, selects an available capability, executes a real read-only product operation and returns evidence.
- A sensitive operation pauses for approval and cannot execute without it.
- Unavailable products are shown as unavailable, never simulated as connected.
- Tests and build commands are recorded with their actual results before release.
