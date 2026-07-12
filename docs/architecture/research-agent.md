# Research Agent architecture

```text
Browser POST goal -> Django API -> Redis/Celery agent queue -> LangGraph
                                             |              |-- planner
                                             |              |-- public tools
                                             |              |-- synthesizer
                                             |              `-- verifier/replan
                                             v
                              MySQL run/event/tool trace <- result
                                             |
Browser SSE (stable event ID / resume) <------'
```

Public tools are read-only. High-risk repair tools live in a separate staff registry and execute only after a persisted `AgentApproval`. Content indexing is updated after the content transaction commits. Redis uses AOF; MySQL is the durable source of truth for runs and events.

Runs move through queued, planning, executing, verifying and a terminal state. The verifier accepts an evidence-backed answer or an explicit insufficient-evidence answer. Failed verification can replan once; bounded steps and terminal checks prevent infinite loops. Cancellation is durable and emits an event.

Trust boundaries:

- Scraped text is untrusted evidence, never instructions.
- Fetch and OCR validate initial and redirected URLs and reject private/reserved targets.
- Public tools cannot resolve staff tools. Repair actions require staff approval and an idempotency key.
- Public mode is stateless until HTTPS is available; session memory is opt-in.

The 2C2G deployment uses one web worker, one general worker and one single-concurrency Agent worker. This isolates long model/tool calls from crawling and avoids claiming unmeasured high concurrency.
