# Research Agent API

Create a run with `POST /api/v1/research-runs` and JSON `{"goal":"...","client_request_id":"unique-at-least-8-chars"}`. Repeating the client request ID returns the original run and does not enqueue twice.

- `GET /api/v1/research-runs/{id}`: current/terminal state and metrics.
- `GET /api/v1/research-runs/{id}/events`: SSE. Send `Last-Event-ID` or `?after=N` to resume; `?snapshot=1` returns persisted events only.
- `POST /api/v1/research-runs/{id}/cancel`: idempotent cancellation.
- `POST /api/v1/research-runs/{id}/replay`: new run with frozen goal, graph version and prompt version, plus lineage.

New requests have per-IP daily and concurrent limits. UUID run IDs are capability-like but are not authentication; private user data must not be exposed through this public API.
