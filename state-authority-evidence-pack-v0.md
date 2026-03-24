# State Authority Evidence Pack v0

**Source**: 5 real harness traces via Aegis P0+P1 pipeline  
**Date**: 2026-03-24  
**Purpose**: Drive State Authority design from evidence, not speculation

---

## Trace Summary

| ID | Task | Agent Selected | Candidates | Tokens | Duration | Status |
|----|------|---------------|------------|--------|----------|--------|
| trace-1 | Simple code review | engineering.code-reviewer | 2 evaluated, 0 filtered | 384 | 6.3s | OK |
| trace-2 | Two-candidate routing | engineering.explainer | 2 evaluated, 0 filtered | 926 | 14.7s | OK |
| trace-3 | Clean failure | — | 0 matched | 0 | 0.0s | FAIL (routing) |
| trace-4 | Structured output (schema) | engineering.schema-designer | 1 evaluated, 0 filtered | 1,205 | 11.1s | OK |
| trace-5 | Report generation | product.report-writer | 1 evaluated, 0 filtered | 1,165 | 21.3s | OK |

**Total API cost**: ~3,680 tokens across 4 successful dispatches.

---

## Trace Details

### Trace 1: Simple Single-Agent Task

**Task**: Review a Python function for bugs (division by zero in `calculate_average`).

**Routing**: 2 candidates (code-reviewer, explainer). Code-reviewer won with +25 preferred capability, +15 specialization, -20 cost risk = **20.0**. Explainer scored **-20.0** (cost risk only, no preferred match).

**Dispatch**: Code-reviewer identified the division-by-zero bug correctly. Output was structured (headings, bug list, fix suggestion). 384 tokens, 6.3s.

**Observations**:
- Routing differentiation worked. Preferred capability was the decisive factor.
- The -20 cost_time_ratio penalty hit both agents equally (both default 300s timeout vs 120s budget). This penalty is noisy — it doesn't differentiate agents, it punishes the default environment config.
- Output was well-structured without explicit format instructions. Agent constraints ("be_concise", "focus_on_bugs") were followed.

---

### Trace 2: Two Plausible Candidates

**Task**: Analyze merge_sorted code — both review and explain are valid approaches.

**Routing**: 2 candidates tied at **-20.0** each. No preferred capabilities specified, so no differentiation. Explainer won by being first in the registry's iteration order (not by merit).

**Dispatch**: Explainer produced a detailed analysis with analogies ("like merging two organized filing cabinets"). 926 tokens, 14.7s.

**Observations**:
- **Tie-breaking is arbitrary.** With no preferred capabilities and no historical data, tied agents are ordered by iteration order. The spec says "prefer lower estimated cost" but both have the same environment config.
- **This is where historical performance data would matter.** If the experience store had data showing code-reviewer produces better analysis output, it would break the tie.
- The explainer's output was longer and more pedagogical — arguably wrong for a "what does this do and any issues" task. The code-reviewer might have been better.
- **Evidence for State Authority**: recording which agent was selected AND what the output quality looked like is essential for future routing improvement.

---

### Trace 3: Clean Failure

**Task**: Deploy to production (no agent has `deploy_service` capability).

**Routing**: Failed at filter phase. 0 candidates matched. Returned `RoutingFailure` with `no_suitable_agent` reason and missing capabilities list.

**Dispatch**: Never reached. stage_failed = "routing".

**Observations**:
- Failure path is clean and fast (0.0s, no tokens consumed).
- The structured failure includes enough information for the orchestrator to decide next steps (retry with different capabilities, escalate, terminate).
- **Evidence for State Authority**: routing failures must be recorded as events. An orchestrator needs to know "this step was attempted and failed at routing" vs "this step was never attempted."

---

### Trace 4: Structured Output (Schema Design)

**Task**: Design a PostgreSQL schema for a task management system, with structured context.

**Routing**: 1 candidate (schema-designer). No competition. Score -20.0 (cost risk only).

**Dispatch**: Produced well-formed CREATE TABLE statements. 1,205 tokens, 11.1s. The agent followed constraints ("use_postgresql", "normalize_to_3nf"). Task context (database type, requirements list) was successfully injected into the prompt.

**Observations**:
- **Task context injection works.** The structured context dict was correctly serialized and included in the user message.
- **Output is machine-parseable.** The schema output could be validated against a schema evaluator (does it contain valid SQL? does it cover all required tables?). This is exactly where `output_schemas` validation would add value.
- **Single-candidate routing is common.** When only one agent matches, scoring is irrelevant — the agent is selected by capability filter alone. The score (-20.0) is meaningless noise.
- **Evidence for State Authority**: for single-candidate tasks, the routing trace is lightweight. Don't over-engineer event recording for trivial routing decisions.

---

### Trace 5: Report Generation (Evaluation Boundary)

**Task**: Technical assessment of event sourcing vs CRUD for multi-agent state layers.

**Routing**: 1 candidate (report-writer). Score -20.0.

**Dispatch**: Produced a 4,849-character structured report with executive summary, pros/cons comparison, and recommendation. 1,165 tokens, 21.3s. Agent followed constraints ("structured_output", "include_executive_summary").

**Observations**:
- **Longest execution.** 21.3s is within the 120s budget but notably longer than other tasks. If this were part of a workflow, other steps would be waiting.
- **Output quality is the real question.** The report exists and is structured, but is it *good*? The current system has no way to evaluate "is this analysis correct?" — only "did the agent produce output that matches structural criteria."
- **Constraint adherence is visible.** "include_executive_summary" was followed. "structured_output" was followed. These are observable, checkable conditions.
- **Evidence for State Authority**: evaluation events need to distinguish structural compliance (format is correct) from quality assessment (content is correct). These are different evaluator classes.

---

## Design Question Answers

### Q1: What are the minimum canonical event types?

Based on the 5 traces, the events that actually occurred and would need recording:

**Required (observed in every trace)**:
| Event Type | When | What it Records |
|---|---|---|
| `task.created` | Pipeline receives task | Task descriptor (capabilities, inputs, risk, budget) |
| `task.routed` | Router returns result | Primary agent, fallbacks, scores, reasoning, candidates evaluated/filtered |
| `task.completed` | Dispatch succeeds | Agent ID, output summary, tokens, duration |
| `task.failed` | Dispatch or routing fails | Stage failed, reason, detail |

**Required (observed in subset)**:
| Event Type | When | What it Records |
|---|---|---|
| `task.skipped` | Routing finds no candidates | Missing capabilities, 0 candidates |

**NOT yet observed but implied by traces**:
| Event Type | When | Why Needed |
|---|---|---|
| `task.started` | Agent begins execution | Marks transition from "routed" to "executing" — needed for timeout/budget tracking |
| `task.retried` | Fallback attempted | Trace 2 could have triggered this if primary failed |
| `agent.output` | Raw output stored | For replay, audit, quality review |

**NOT needed at this stage**:
| Event Type | Why Deferred |
|---|---|
| `context.updated` | No multi-step workflows ran — no shared context to update |
| `governor.decision` | Admission was pass/fail — no complex governance decisions recorded |
| `budget.reserved/committed/released` | No budget tracking active in harness |
| `workflow.*` | No workflows — single-task harness only |
| `monitor.*` | No runtime monitor active |

**Verdict**: Start with 6 event types: `task.created`, `task.routed`, `task.started`, `task.completed`, `task.failed`, `agent.output`. Add workflow/governance/budget events when those systems come online. Don't build what the traces don't demand.

---

### Q2: What projections are actually needed?

Based on the traces, two projections are immediately useful:

**1. Task Lifecycle Projection**

Needed now. Every trace follows the same lifecycle:
```
created → routed → started → completed/failed
```

This projection should answer:
- What state is task X in right now?
- How long has it been in the current state?
- What was the routing decision?
- What was the output?

**2. Agent Execution History Projection**

Needed for routing improvement. Traces 1 and 2 show that without historical data, routing quality degrades (ties, arbitrary selection). This projection should answer:
- What is agent X's success rate for task type Y?
- What is agent X's average latency for task type Y?
- Has agent X failed recently?

This directly feeds the `ExperienceStore` protocol already stubbed in P1.

**Not needed yet**:
- **Workflow Context Projection**: no multi-step workflows ran.
- **Budget Projection**: no budget tracking active.
- **Governance Audit Projection**: admission was trivial in all traces.

**Verdict**: Build 2 projections first. Task Lifecycle and Agent Execution History. These are the ones the traces actually need.

---

### Q3: What conflicts are real?

Based on 5 single-task traces: **none observed.**

No parallel writes occurred. No shared context was updated. No two agents competed for the same state key.

**However**, Trace 2 reveals where conflicts WILL occur:
- Two agents were candidates for the same task. In a workflow with fork/join, both could run in parallel and write to the same context namespace.
- If both produce `review_report` output, the join step needs to merge or select.

**Verdict**: Don't build the full 4-class conflict resolution system yet. Start with `append_only` for `agent.output` events (the only write type observed) and `replaceable` for task lifecycle state. Add `mergeable` and `exclusive` when fork/join traces demand them.

---

### Q4: What should be scoped?

Based on the traces:

| Data | Observed Scope | Reasoning |
|---|---|---|
| Task descriptor | Workflow-local (or task-local) | Each task is independent. No cross-task visibility needed. |
| Routing decision | Task-local | Routing reasoning is specific to one task. |
| Agent output | Task-local | Output belongs to the task that requested it. |
| Agent execution history | Global | The experience store feeds ALL routing decisions, not just one workflow. |
| Task lifecycle state | Task-local | "What state is task X in?" is per-task. |

**Verdict**: Default scope should be task-local. Only agent execution history (the experience store) is global. This is simpler than the spec's 3-tier model and matches what the traces actually show.

---

### Q5: What deserves snapshotting?

Based on 5 traces with total execution time of ~53 seconds and ~3,680 tokens:

**Nothing yet.**

Snapshotting is for replay optimization when event logs grow large. With single-task traces completing in 6-21 seconds, the event log for any single task is 4-6 events. Replay from scratch is instant.

**When snapshotting will matter**:
- Workflows with 10+ steps
- Agent execution history after 100+ tasks
- Budget state across long-running workflows

**Verdict**: Defer snapshotting entirely. Build the event log and projections without it. Add snapshots when replay latency becomes measurable.

---

## Unresolved Questions

### U1: Cost risk penalty is too uniform

Every agent scored -20.0 on `cost_time_ratio` because all use the default 300s timeout against the default 120s task budget. This penalty doesn't differentiate — it's just noise. Options:
- Remove default cost_time_ratio penalty when both values are defaults
- Only apply when agent has a custom timeout that's notably high
- Weight this penalty lower until real cost data exists

### U2: Tie-breaking needs a better heuristic

Trace 2 shows two agents tied at -20.0. The winner was determined by iteration order, not by any meaningful signal. Without historical data, ties will be common for agents with similar capability profiles. Options:
- Random selection for true ties (at least it's honest)
- Prefer the agent with fewer capabilities (specialist heuristic)
- Require preferred_capabilities to be specified when multiple agents match

### U3: Output quality is not measurable

Traces 4 and 5 produced large, structured outputs. The system can verify:
- Did the agent produce output? (yes/no)
- Is the output non-empty? (length check)
- Did the agent follow constraint keywords? (string match)

It cannot verify:
- Is the schema normalized to 3NF?
- Is the report's analysis correct?
- Is the code review comprehensive?

This is the evaluation gap. Structural evaluators are implementable. Quality evaluators may require a second LLM pass or human review.

### U4: Single-candidate routing is over-instrumented

Traces 4 and 5 had exactly 1 candidate each. The full scoring pipeline (preferred match, specialization, cost risk) ran but produced no useful differentiation. For single-candidate tasks, the routing trace could be simplified to "1 candidate, admitted, dispatched."

### U5: Task budget defaults don't match agent defaults

Default task budget: 120s. Default agent timeout: 300s. This mismatch means every agent with default config gets a cost penalty. Either the defaults should align or the cost_time_ratio scorer should handle default-vs-default as neutral.

---

## Recommended State Authority Build Order

Based on the evidence:

| Priority | Component | Justification |
|---|---|---|
| **1** | Event model (6 types) | Every trace needs these recorded |
| **2** | Append-only event log | Storage for events |
| **3** | Task Lifecycle Projection | Answers "what state is this task in?" |
| **4** | Agent Execution History Projection | Feeds ExperienceStore, improves routing |
| **5** | Sequencer (monotonic ordering) | Needed before parallelism |
| **6** | Scoped read rules (task-local + global) | Simple 2-tier model |
| **Defer** | Conflict classes beyond replaceable/append_only | No parallel writes observed |
| **Defer** | Snapshots | Event logs are tiny at this scale |
| **Defer** | Workflow/governance/budget events | No orchestrator active |
| **Defer** | Namespace-level write permissions | No multi-agent context sharing observed |

**Start with items 1-4. That's the minimum viable state layer.**
