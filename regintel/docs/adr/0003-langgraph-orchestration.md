# ADR-0003: LangGraph for agent orchestration

- **Status:** Accepted
- **Date:** 2026-11-07

## Context
Document checks are multi-step (classify, extract, retrieve per requirement, compare, draft),
must pause for a human reviewer for minutes or days, survive restarts, and be testable node by
node.

## Options considered
1. **Plain Python pipeline** - simplest; no durable pause/resume; we would re-invent checkpoints.
2. **Autonomous agent loop (ReAct with tools)** - flexible, but non-deterministic paths, harder to
   bound cost, larger prompt-injection blast radius.
3. **CrewAI / AutoGen-style multi-agent chat** - good for open-ended collaboration; weak typing
   of state, conversation-shaped rather than workflow-shaped.
4. **LangGraph** - explicit typed state graph, conditional edges, `interrupt()` for
   human-in-the-loop, pluggable checkpointers (memory / Postgres).
5. **Temporal** - excellent durability; heavier operationally; LLM-specific ergonomics are DIY.

## Decision
LangGraph with a fixed graph (not an autonomous agent): the control flow is code, the LLM only
fills typed slots. Postgres checkpointer in production; memory in tests. Long checks can be
moved off the API with the Redis queue worker; Temporal remains an option if checks become
multi-day workflows with external callbacks.

## Consequences
- Positive: deterministic path, bounded steps/cost, each node unit-tested with a fake LLM,
  restart-safe review, natural trust boundary between quarantined and privileged nodes.
- Negative: less flexible than a free-form agent; adding a step means changing the graph.
- Follow-ups: per-node retry policies; parallel fan-out of `compare` per requirement.

## How we will know it was right
Check-suite metrics (gap recall/precision, steps per run) stay stable as requirements are added;
reviewers can resume checks after deploys.
