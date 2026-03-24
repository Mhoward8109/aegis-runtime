# Aegis Runtime Contracts v1.2

**Status**: Approved for P0 Implementation  
**Compatibility Target**: Agent-OS v1.0.0 + P0/P1 codebase  
**Date**: 2026-03-23  
**Revision**: v1.2 — incorporates 9 P1-blocking net-new fixes from conformance audit  
**Author**: FORGE–Aegis Hybrid

---

## Revision Log

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-03-18 | Initial five-contract spec |
| v1.1 | 2026-03-18 | 12 audit corrections + 6 suggested additions incorporated |
| v1.2 | 2026-03-23 | 9 P1-blocking net-new fixes. See §Changelog v1.1→v1.2 at end of document. |

---

## Document Purpose

Five canonical contracts that define the executable runtime layer for the Aegis agent architecture. Each contract specifies the data model, behavioral rules, and integration surface required for implementation.

These contracts are **prescriptive, not descriptive**. Code that violates them is non-conformant.

---

# Contract 1: Agent Schema v1.1

## 1.1 Purpose

Define the structure every agent must conform to in order to be registered, discovered, routed to, evaluated, and governed.

## 1.2 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AegisAgentSpec",
  "type": "object",
  "required": [
    "agent_id",
    "version",
    "status",
    "role",
    "capabilities",
    "required_inputs",
    "outputs",
    "tools",
    "constraints",
    "evaluation"
  ],
  "properties": {
    "agent_id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9-]*\\.[a-z][a-z0-9-]*$",
      "description": "Namespaced identifier: domain.agent-name"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "SemVer. See §1.4 for versioning rules."
    },
    "status": {
      "type": "string",
      "enum": ["active", "deprecated", "experimental", "suspended"],
      "description": "Only 'active' agents are routable by default."
    },
    "role": {
      "type": "string",
      "description": "Human-readable role label."
    },
    "capabilities": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1,
      "description": "Machine-matchable capability tags from controlled vocabulary. Router indexes on these."
    },
    "required_inputs": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Named input types this agent MUST receive to execute. Router filters on these."
    },
    "optional_inputs": {
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "Named input types this agent CAN consume but does not require. Router does not filter on these."
    },
    "outputs": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Named output types this agent produces."
    },
    "output_schemas": {
      "type": "object",
      "additionalProperties": { "type": "string" },
      "default": {},
      "description": "Map of output_name → JSON Schema reference path. Enables evaluator to validate output structure. Example: { 'ui_code': 'schemas/ui_code_v1.json' }"
    },
    "tools": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Tools this agent is permitted to invoke."
    },
    "constraints": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Hard rules the agent must obey. Violations trigger evaluator."
    },
    "depends_on": {
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "Agent IDs that must have produced output before this agent can execute."
    },
    "required_inputs_from": {
      "type": "object",
      "additionalProperties": { "type": "string" },
      "default": {},
      "description": "Map of input_name → source_agent_id. Declares explicit data lineage."
    },
    "environment": {
      "type": "object",
      "properties": {
        "runtime": {
          "type": "string",
          "enum": ["python", "node", "shell", "any"],
          "default": "any"
        },
        "sandbox_required": {
          "type": "boolean",
          "default": true
        },
        "max_execution_seconds": {
          "type": "integer",
          "default": 300
        }
      },
      "default": {}
    },
    "evaluation": {
      "type": "object",
      "required": ["success_criteria"],
      "properties": {
        "success_criteria": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1
        },
        "evaluator_classes": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": [
              "schema",
              "tool_result",
              "policy",
              "budget",
              "human_gate",
              "quality_heuristic"
            ]
          },
          "default": ["schema", "policy"]
        },
        "max_retries": {
          "type": "integer",
          "default": 2,
          "maximum": 5
        },
        "circuit_breaker_on": {
          "type": "array",
          "items": { "type": "string" },
          "default": ["invalid_output_schema", "policy_violation"],
          "description": "Failure modes that skip retry and escalate immediately."
        }
      }
    },
    "metadata": {
      "type": "object",
      "properties": {
        "author": { "type": "string" },
        "created": { "type": "string", "format": "date" },
        "changelog": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "version": { "type": "string" },
              "date": { "type": "string", "format": "date" },
              "note": { "type": "string" }
            }
          }
        }
      }
    }
  }
}
```

## 1.3 Rules

| Rule | Enforcement |
|------|-------------|
| `agent_id` must be unique within the registry | Registry rejects duplicates at registration time |
| `version` must follow SemVer rules in §1.4 | Registry validates version increment semantics |
| `status: deprecated` agents remain discoverable but unroutable | Router filters on status before scoring |
| `status: suspended` agents are invisible to router and registry queries | Manual reactivation only |
| `capabilities` tags must come from controlled vocabulary | Registry maintains canonical capability list; unknown tags rejected |
| `tools` entries must exist in the tool permission registry | Governor validates tool access at admission control |
| `depends_on` creates a hard DAG constraint | Orchestrator must resolve dependency order before execution |
| `circuit_breaker_on` failures bypass retry and escalate to governance | Evaluator enforces; no override without policy change |
| `output_schemas` references must resolve to valid JSON Schema files | Registry validates at registration time. Unresolvable references are rejected before the agent enters the registry. Evaluation-time schema resolution is NOT permitted — all schemas must be available at registration. |
| `required_inputs` are the ONLY inputs used for router filtering | `optional_inputs` never cause routing exclusion |

## 1.4 Versioning Rules

SemVer increments are classified by change type to prevent noisy enforcement:

| Bump | Trigger | Examples |
|------|---------|----------|
| **Major** (X.0.0) | Breaking change to `required_inputs`, `outputs`, `output_schemas`, `depends_on`, `required_inputs_from`, or `tools` | Removing a required input, changing output schema shape, dropping a tool dependency |
| **Minor** (x.Y.0) | Additive or behavioral change to `capabilities`, `optional_inputs`, `evaluation`, `constraints`, or `environment` | Adding a new capability, changing retry count, adding an evaluator class |
| **Patch** (x.y.Z) | Non-execution changes to `metadata`, `role`, documentation, or `changelog` | Fixing a typo in role description, updating author |

**Enforcement**: The registry validates that registered version increments match the diff between old and new spec. Undersized bumps (e.g., breaking I/O change with only a patch bump) are rejected.

## 1.5 Agent-OS Mapping

| Schema Field | Agent-OS v1.0.0 Equivalent | Gap |
|---|---|---|
| `agent_id` | Agent class `name` attribute | Needs namespace convention enforcement |
| `capabilities` | Implicit in agent class behavior | Needs explicit capability registry |
| `evaluation` | Partial — exists in test harness | Needs runtime evaluator integration |
| `environment` | Subprocess sandbox exists | Needs per-agent config binding |
| `required_inputs` / `optional_inputs` | Single `inputs` list | Needs split + router integration |
| `output_schemas` | Not implemented | Needs schema registry + evaluator binding |

---

# Contract 2: Router Contract v1.1

## 2.1 Purpose

Define how tasks are matched to agents. The router is the central decision engine — it takes a task descriptor and returns a ranked list of candidate agents.

## 2.2 Task Descriptor

Every routable task must conform to this structure:

```json
{
  "task_id": "uuid",
  "type": "string",
  "required_capabilities": ["string"],
  "preferred_capabilities": ["string"],
  "inputs_available": ["string"],
  "priority": "critical | high | normal | low",
  "routing_mode": "single | ranked | ensemble | manual_review",
  "budget": {
    "max_tokens": 50000,
    "max_cost_usd": 0.50,
    "max_duration_seconds": 120
  },
  "context_ref": "string | null",
  "origin": {
    "source": "user | orchestrator | agent",
    "source_id": "string"
  },
  "constraints": {
    "require_sandbox": true,
    "allowed_tools": ["string"]
  }
}
```

### Routing Modes

| Mode | Behavior |
|------|----------|
| `single` | Return the top-scoring agent only. Default mode. |
| `ranked` | Return top N candidates with scores. Orchestrator or user selects. |
| `ensemble` | Dispatch task to top N agents in parallel. Outputs merged by orchestrator. |
| `manual_review` | Return ranked candidates but require human selection before dispatch. |

## 2.3 Routing Algorithm

```
ROUTE(task) → RoutingResult

1. FILTER phase (hard gates — any failure = exclusion)
   a. agent.status == "active"
   b. task.required_capabilities ⊆ agent.capabilities
   c. task.inputs_available ⊇ agent.required_inputs
      (NOTE: filters against required_inputs ONLY, not optional_inputs)
   d. task.constraints.allowed_tools ⊇ agent.tools (if specified)
   e. agent.environment compatible with current runtime
   f. Governor.admissionCheck(task, agent) == PASS

2. SCORE phase (weighted ranking)
   a. capability_match:
      - required match:    baseline (already filtered)
      - preferred match:   +25 per matched preferred capability
      - specialization:    +15 if agent.capabilities overlap ratio > 0.7
                           (i.e., most of the agent's capabilities are relevant)

   b. context_relevance:
      - agent recently succeeded on similar task type: +30
      - agent has warm context from current workflow:  +20
      - agent is cold (no recent activity):            +0

   c. historical_performance:
      - success_rate for this task type:  weight * success_rate (weight = 40)
      - average_latency penalty:          -1 per second above median
      - failure_recency:                  -50 if failed same task type in last 3 runs

   d. cost_risk:
      - estimated_cost / budget.max_cost_usd > 0.8:  -20
      - agent flagged for budget overruns:             -30

   TOTAL_SCORE = capability_match + context_relevance
                 + historical_performance - cost_risk

3. RANK phase
   - Sort candidates by TOTAL_SCORE descending
   - If top score < MINIMUM_CONFIDENCE_THRESHOLD (configurable, default 50):
     return NO_SUITABLE_AGENT → escalate to governance

4. RETURN (per routing_mode)
   - single:        candidates[0]
   - ranked:        candidates[0..N] with scores
   - ensemble:      candidates[0..N] flagged for parallel dispatch
   - manual_review: candidates[0..N] with scores, held for human selection
   - All modes:     include scores and reasoning trace for audit log
```

### Scoring Note: Specialization vs. Excess Capability

v1.0 penalized agents for having capabilities beyond what the task required (-5 per unneeded capability). This was removed because:

- Multi-capable agents were unfairly penalized for general usefulness
- Capability count is not a reliable proxy for overfit or risk
- Cost, performance history, and tool exposure already capture the real risks

Replaced with a **specialization bonus**: agents whose capability set closely matches the task requirements (overlap ratio > 0.7) receive +15. This rewards focus without punishing breadth.

## 2.4 Router State

The router is **stateless per invocation** but reads from:

| Source | Data |
|--------|------|
| Agent Registry | Agent specs, status, capabilities |
| Experience Store | Historical performance metrics |
| Governor | Admission control decisions, budget state |
| State Authority | Current workflow context, warm agent cache |

The router **never writes** to these stores. It is a pure query-and-rank function. Side-effect-free routing enables safe retries and parallel evaluation.

## 2.5 Failure Modes

| Failure | Response |
|---------|----------|
| No agents match required capabilities | Return `NO_SUITABLE_AGENT` with missing capability list |
| All candidates fail admission control | Return `BLOCKED_BY_GOVERNANCE` with denial reasons |
| Registry unavailable | Return `REGISTRY_UNAVAILABLE` — orchestrator must retry or halt |
| Score tie | Prefer agent with lower estimated cost; if still tied, prefer most recently successful |

**Advisory vs. authoritative admission**: The router's admission check in the filter phase (step 1f) is advisory — it is a point-in-time check that may become stale under parallel execution (e.g., budget consumed by a concurrent step between routing and dispatch). The authoritative admission check occurs at dispatch time in the orchestrator. If the dispatched agent fails the authoritative admission check:

1. The orchestrator attempts the next fallback candidate from the router's ranked list.
2. If all fallback candidates fail admission, the orchestrator emits a `task.failed` event with classification `all_candidates_denied` and follows the step's `on_fail` handler.
3. The router is NOT re-invoked automatically. Re-routing requires explicit orchestrator logic or step retry.

## 2.6 Agent-OS Mapping

| Router Component | Agent-OS v1.0.0 Equivalent | Gap |
|---|---|---|
| Task descriptor | Partial — task dict exists | Needs formal schema validation + routing_mode |
| Filter phase | Basic capability check exists | Needs required_inputs filtering, tool permission, governor integration |
| Score phase | Not implemented | Full implementation needed |
| Experience lookups | Not implemented | Needs experience store integration |
| Routing modes | Not implemented | Full implementation needed |

---

# Contract 3: State Authority Model v1.1

## 3.1 Purpose

Define how runtime state is stored, accessed, scoped, and protected. The state authority replaces flat shared JSON with an event-sourced model that supports concurrency, auditability, and rollback.

## 3.2 Core Principles

1. **Events are immutable facts.** Once written, events are never modified or deleted (only superseded).
2. **State is derived.** Current state is always a projection of the event log. No mutable shared blob.
3. **Access is scoped.** Agents see only what their scope permits (read AND write scoping).
4. **Writes are arbitrated.** Concurrent writes go through a sequencer with typed conflict resolution.

## 3.3 Event Schema

```json
{
  "event_id": "uuid",
  "idempotency_key": "string | null",
  "timestamp": "ISO-8601",
  "event_type": "string",
  "source": {
    "type": "agent | orchestrator | governor | user",
    "id": "string"
  },
  "scope": "global | workflow:<id> | agent:<id>",
  "payload": {},
  "causation_id": "uuid | null",
  "correlation_id": "uuid"
}
```

### Idempotency

If `idempotency_key` is provided, the sequencer checks for a prior event with the same key. If found, the write is acknowledged but not re-appended. This enables safe retries for agents and the orchestrator without event duplication.

### Event Types (canonical set, extensible)

| Event Type | Payload | Scope |
|------------|---------|-------|
| `task.created` | Task descriptor | workflow |
| `task.routed` | Agent ID, score, alternatives | workflow |
| `task.started` | Agent ID, start time | workflow |
| `task.completed` | Agent ID, output summary, metrics | workflow |
| `task.failed` | Agent ID, failure classification, error | workflow |
| `task.retried` | Agent ID, retry count, reason | workflow |
| `task.skipped` | Reason, condition that evaluated false | workflow |
| `agent.output` | Output data (or ref to external storage) | workflow |
| `context.updated` | Key, value, conflict_class, namespace | workflow or global |
| `governor.decision` | Decision type, result, reasoning | workflow |
| `governor.warning` | Warning type, details | workflow |
| `governor.violation` | Violation type, agent, details | workflow |
| `workflow.started` | Workflow spec, initiator | workflow |
| `workflow.completed` | Final status, summary metrics | workflow |
| `workflow.terminated` | Reason, initiator | workflow |
| `monitor.warning` | Warning type, agent, threshold, current value | workflow |
| `monitor.interrupt` | Interrupt reason, agent, action taken | workflow |
| `budget.reserved` | Task ID, amount, expires_at | workflow |
| `budget.committed` | Task ID, amount | workflow |
| `budget.released` | Task ID, amount, reason (completed/expired/cancelled) | workflow |
| `budget.expired` | Task ID, amount | workflow |
| `trust.recommendation` | Agent ID, current tier, recommended tier, evidence | global |

## 3.4 State Projections

Current state is computed by replaying events through projection functions:

```python
class WorkflowProjection:
    """Derives current workflow state from event stream."""

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.status = "pending"
        self.completed_tasks: dict[str, dict] = {}
        self.active_task: str | None = None
        self.context: dict[str, ContextEntry] = {}
        self.budget_consumed: float = 0.0

    def apply(self, event: Event) -> None:
        match event.event_type:
            case "task.completed":
                self.completed_tasks[event.payload["task_id"]] = event.payload
                self.active_task = None
            case "task.started":
                self.active_task = event.payload["agent_id"]
            case "context.updated":
                self._apply_context_update(event)
            case "workflow.completed":
                self.status = "completed"
            case "workflow.terminated":
                self.status = "terminated"
            # ... remaining handlers

    def _apply_context_update(self, event: Event) -> None:
        """Apply context update with typed conflict resolution."""
        key = event.payload["key"]
        value = event.payload["value"]
        conflict_class = event.payload.get("conflict_class", "replaceable")

        match conflict_class:
            case "replaceable":
                # Last-event-wins. Only valid for explicitly replaceable fields.
                self.context[key] = ContextEntry(
                    value=value,
                    source=event.source,
                    timestamp=event.timestamp,
                    conflict_class=conflict_class
                )
            case "mergeable":
                # Structured merge. Value must be a dict or list.
                existing = self.context.get(key)
                if existing and isinstance(existing.value, dict) and isinstance(value, dict):
                    merged = {**existing.value, **value}
                    self.context[key] = ContextEntry(
                        value=merged, source=event.source,
                        timestamp=event.timestamp, conflict_class=conflict_class
                    )
                elif existing and isinstance(existing.value, list) and isinstance(value, list):
                    self.context[key] = ContextEntry(
                        value=existing.value + value, source=event.source,
                        timestamp=event.timestamp, conflict_class=conflict_class
                    )
                else:
                    self.context[key] = ContextEntry(
                        value=value, source=event.source,
                        timestamp=event.timestamp, conflict_class=conflict_class
                    )
            case "exclusive":
                # Reject second write unless from same source or authorized.
                existing = self.context.get(key)
                if existing and existing.source.id != event.source.id:
                    raise ConflictError(
                        f"Exclusive key '{key}' already written by {existing.source.id}"
                    )
                self.context[key] = ContextEntry(
                    value=value, source=event.source,
                    timestamp=event.timestamp, conflict_class=conflict_class
                )
            case "append_only":
                # Always append, never overwrite.
                existing = self.context.get(key)
                if existing and isinstance(existing.value, list):
                    existing.value.append(value)
                    existing.timestamp = event.timestamp
                else:
                    self.context[key] = ContextEntry(
                        value=[value], source=event.source,
                        timestamp=event.timestamp, conflict_class=conflict_class
                    )
```

### Conflict Classes

| Class | Behavior | Use Case |
|-------|----------|----------|
| `replaceable` | Last-event-wins within sequenced order | Status fields, current values, transient flags |
| `mergeable` | Dict merge (union keys) or list concatenation | Accumulated findings, combined recommendations |
| `exclusive` | Reject second write from different source | Final decisions, authoritative claims, single-owner fields |
| `append_only` | Always append to list, never overwrite | Logs, observation lists, incremental evidence |

Every `context.updated` event MUST declare its `conflict_class`. Events without a conflict class are rejected by the sequencer.

## 3.5 Scoping Rules

### Read Scope

| Agent Scope Level | Can Read |
|-------------------|----------|
| `global` | Global context, own workflow events |
| `workflow:<id>` | All events in that workflow |
| `agent:<id>` | Only own events |

**Default scope for agents**: `workflow:<current>` — agents in a workflow can see workflow-level state but cannot see other workflows or global state unless explicitly granted.

### Write Scope

Write permissions are scoped by **event type AND namespace**, not just by scope level.

| Permission | Meaning | Example |
|-----------|---------|---------|
| `agent.output` | Agent can emit its own outputs | All agents have this by default |
| `context.updated:<namespace>` | Agent can write to a specific context namespace | `context.updated:working_notes`, `context.updated:research_findings` |
| `context.updated:*` | Agent can write to any context namespace | Granted only to orchestrator and privileged agents |

**Default write permissions for agents**:
- `agent.output` — always granted
- `context.updated:working_notes` — granted by default
- All other writes require explicit grant in the workflow spec or governor approval

**Scope escalation** requires governor approval and is logged as a `governor.decision` event.

### Context Namespaces (starter set)

| Namespace | Owner | Conflict Class |
|-----------|-------|----------------|
| `working_notes` | Any agent | `append_only` |
| `research_findings` | Research agents | `mergeable` |
| `budget_estimate` | Orchestrator | `exclusive` |
| `final_decision` | Orchestrator / Human | `exclusive` |
| `task_parameters` | Orchestrator | `replaceable` |
| `quality_scores` | Evaluator agents | `mergeable` |

## 3.6 Write Arbitration

All writes pass through a sequencer:

```
WRITE(event) → Result

1. Validate event schema
2. If idempotency_key provided, check for duplicate:
   - If duplicate found: return existing event confirmation (no re-append)
3. Check source has write permission for declared scope + event type + namespace
4. Validate conflict_class is declared on context.updated events
5. Assign monotonic sequence number
6. Append to event log
7. Notify active projections
8. Return confirmation with sequence number
```

Concurrent writes from parallel agents are serialized by the sequencer. Conflict resolution happens at the projection layer using the declared `conflict_class` for each field. This replaces the v1.0 blanket last-event-wins default.

## 3.7 Snapshots and Retention

| Mechanism | Behavior |
|-----------|----------|
| **Snapshots** | Projection state serialized every N events (configurable, default 100). Replay starts from latest snapshot. |
| **Retention** | Events older than `ttl_days` (default 30) are archived, not deleted. Archived events are available for replay but not in hot path. |
| **Max recent outputs** | Configurable cap (default 100) on `agent.output` events in hot storage per workflow. Older outputs archived. |
| **Rollback** | Reset projection to a named snapshot. Does not delete events — projects forward from snapshot, skipping events after rollback point. See §4.8 for rollback classes. |

## 3.8 Agent-OS Mapping

| State Authority Component | Agent-OS v1.0.0 Equivalent | Gap |
|---|---|---|
| Event log | Partial — execution log exists | Needs event schema, immutability, idempotency |
| Projections | Not implemented | Full implementation needed |
| Conflict classes | Not implemented | Full implementation needed |
| Write scoping (event type + namespace) | Not implemented | Full implementation needed |
| Write arbitration | Not implemented (Firestore direct writes) | Core gap — L2 from topology doc |
| Snapshots | Not implemented | Needed for production resilience |

---

# Contract 4: Orchestration Grammar v1.1

## 4.1 Purpose

Define the execution language for multi-agent workflows. The grammar specifies how steps are composed, how control flows, how failures are handled, and how side effects are tracked.

## 4.2 Workflow Schema

```yaml
workflow:
  id: "string (uuid or human-readable)"
  name: "string"
  version: "semver"
  description: "string"

  # Global workflow constraints
  budget:
    max_tokens: 500000
    max_cost_usd: 5.00
    max_duration_seconds: 600

  # Step definitions
  steps:
    - id: "step_id"
      agent: "agent_id"
      type: "task | gate | fork | join"

      inputs: {}
      config: {}

      # Control flow
      depends_on: ["step_id", ...]
      condition: "expression"
      on_success: "next_step_id"
      on_fail: "step_id | terminate | retry | escalate"

      # Side effect declaration (required for task steps with external writes)
      side_effects:
        class: "none | reversible | compensatable | irreversible"
        compensation_step: "step_id | null"

      # Step-level overrides
      budget:
        max_tokens: 50000
      timeout_seconds: 120
      retry:
        max_attempts: 2
        backoff: "linear | exponential"

  # Termination rules
  termination:
    stop_on:
      - "policy_violation"
      - "budget_exceeded"
      - "max_duration_exceeded"
    on_terminate: "rollback | log_and_halt | escalate"
```

## 4.3 Step Types

### `task` — Standard agent execution

```yaml
- id: research
  agent: product.trend-researcher
  type: task
  inputs:
    topic: "{{workflow.params.topic}}"
  side_effects:
    class: none
  on_fail: terminate
```

### `gate` — Conditional checkpoint

Does not invoke an agent. Evaluates a condition and controls flow.

```yaml
- id: quality_check
  type: gate
  condition: "steps.research.output.confidence >= 0.7"
  on_success: synthesize
  on_fail: research_deeper
```

### `fork` — Parallel fan-out

Declares which **previously defined steps** to launch concurrently, and which join step collects results.

**Semantics**: A `fork` step does not define new steps inline. It references step IDs that are defined elsewhere in the `steps` list. The referenced steps are **held from execution** until the fork step is reached, at which point they are released into the ready queue simultaneously.

```yaml
- id: parallel_intake
  type: fork
  branches: [market_research, competitor_analysis, user_feedback]
  join: combine_findings
```

**Rules**:
- All branch step IDs must exist in the `steps` list.
- Branch steps must NOT have `depends_on` pointing to each other (they run in parallel).
- Branch steps must NOT be referenced by other non-fork `depends_on` entries (they are owned by the fork).
- The `join` target must be a step of `type: join`.
- A branch step's only activation path is through its parent fork.

**Partial admission**: If governance denies some but not all branch steps:

1. The fork emits a `task.skipped` event for each denied branch with reason `admission_denied`.
2. The fork proceeds with admitted branches only.
3. If ALL branches are denied, the fork itself fails with classification `all_branches_denied` and follows its `on_fail` handler.

### `join` — Fan-in synchronization

Waits for all incoming branches before proceeding. Collects outputs.

```yaml
- id: combine_findings
  type: join
  expects: [market_research, competitor_analysis, user_feedback]
  merge_strategy: "concatenate | structured_merge | agent_synthesize"
  agent: product.feedback-synthesizer   # required if merge_strategy == agent_synthesize
  timeout_seconds: 300
  on_timeout: "proceed_with_available | terminate"
```

**Terminal state resolution**: A join step considers a branch resolved when it reaches any terminal state: `completed`, `failed`, `skipped`, or `interrupted`. For branches in non-`completed` states, their outputs are absent from the merge set. If `on_timeout: proceed_with_available` is set, the join proceeds with only the completed branch outputs. Without this policy, the join fails if any expected branch did not complete successfully.

## 4.4 Control Flow Primitives

| Primitive | Keyword | Behavior |
|-----------|---------|----------|
| **Sequential** | `depends_on` | Step waits for dependency to complete |
| **Parallel** | `fork` / `join` | Fork releases branch steps concurrently; join synchronizes |
| **Conditional** | `condition` / `gate` | Step executes only if expression evaluates true |
| **Retry** | `retry` block | Re-execute step on failure, with backoff |
| **Branch on failure** | `on_fail: step_id` | Route to alternate step on failure |
| **Terminate** | `on_fail: terminate` | Halt workflow, trigger termination handler |
| **Escalate** | `on_fail: escalate` | Halt workflow, notify governance / human operator |
| **Rollback** | `on_terminate: rollback` | Execute rollback per side-effect class (see §4.8) |

## 4.5 Expression Language

Conditions and input templates use a minimal expression syntax:

```
# Step output references
steps.<step_id>.output.<field>
steps.<step_id>.status          # "completed" | "failed" | "skipped"
steps.<step_id>.metrics.tokens
steps.<step_id>.metrics.cost_usd
steps.<step_id>.metrics.duration_seconds

# Workflow-level references
workflow.params.<key>
workflow.budget.remaining_tokens
workflow.budget.remaining_cost_usd
workflow.elapsed_seconds

# Comparisons
>=  <=  ==  !=  >  <

# Logical operators
and  or  not

# Null literal
null
```

### Null Safety and Missing-Field Semantics

| Scenario | Resolution |
|----------|------------|
| Referenced step does not exist | **Parse-time error.** Workflow is rejected before execution. |
| Referenced step exists but was skipped | `steps.<id>.status` returns `"skipped"`. All output field references return `null`. |
| Referenced output field does not exist | Returns `null`. |
| Comparison against `null` | All comparisons return `false`, EXCEPT `== null` (returns `true`) and `!= null` (returns `true` when value exists). |
| Arithmetic on `null` | Returns `null`. Propagates through expressions. |
| `null` in boolean context | Treated as `false`. |
| Type mismatch (e.g., string >= number) | **Runtime error.** Step fails with `expression_type_error` classification. |
| String/number coercion | **Not supported.** Types must match. Use explicit conversion functions if added in future versions. |

**Static analysis**: The orchestrator parser performs static analysis on expressions at parse time to catch:
- References to undefined step IDs
- Obvious type mismatches where inferable from schema
- Circular references in condition chains

Runtime expressions that cannot be statically validated are evaluated at execution time and fail with clear error classification.

## 4.6 Execution Semantics

1. **DAG resolution**: Before execution, the orchestrator parses the workflow into a directed acyclic graph. Circular dependencies are rejected at parse time. Fork branch steps are validated against fork ownership rules.
2. **Ready queue**: Steps whose dependencies are all satisfied AND whose activation conditions are met (fork-released, or no fork ownership) enter the ready queue.
3. **Input resolution**: Before dispatching a step to the router, the orchestrator MUST populate `task.inputs_available` by collecting all output types declared in the `outputs` field of completed predecessor steps. The orchestrator MUST NOT include output types from steps that failed or were skipped.
4. **Dispatch**: Ready steps are dispatched to the router with the populated task descriptor. The router selects the agent; the orchestrator manages lifecycle.
5. **Event emission**: Every state transition emits an event to the State Authority.
6. **Budget tracking**: Before dispatching each step, the orchestrator checks remaining workflow budget. If insufficient, the step is blocked and governance is notified.
7. **Completion**: Workflow completes when all terminal steps (no downstream dependents) have completed, or when a termination condition fires.

## 4.7 Example: Full Workflow

```yaml
workflow:
  id: product-research-to-prototype
  name: "Product Research → Prototype Pipeline"
  version: "1.0.0"

  budget:
    max_tokens: 300000
    max_cost_usd: 3.00
    max_duration_seconds: 900

  steps:
    # --- Branch steps (owned by parallel_intake fork) ---
    - id: trend_research
      agent: product.trend-researcher
      type: task
      inputs:
        domain: "{{workflow.params.domain}}"
      side_effects:
        class: none
      on_fail: terminate

    - id: feedback_collection
      agent: product.feedback-synthesizer
      type: task
      inputs:
        domain: "{{workflow.params.domain}}"
      side_effects:
        class: none
      on_fail: terminate

    # --- Fork: launches trend_research + feedback_collection in parallel ---
    - id: parallel_intake
      type: fork
      branches: [trend_research, feedback_collection]
      join: synthesis

    # --- Join: waits for both branches ---
    - id: synthesis
      type: join
      expects: [trend_research, feedback_collection]
      merge_strategy: agent_synthesize
      agent: product.insight-combiner
      on_timeout: proceed_with_available
      timeout_seconds: 120

    - id: feasibility_gate
      type: gate
      depends_on: [synthesis]
      condition: "steps.synthesis.output.feasibility_score >= 0.6"
      on_success: prototype
      on_fail: terminate

    - id: prototype
      agent: engineering.rapid-prototyper
      type: task
      depends_on: [feasibility_gate]
      inputs:
        spec: "{{steps.synthesis.output.product_spec}}"
      side_effects:
        class: reversible
      retry:
        max_attempts: 2
        backoff: linear
      on_fail: escalate

    - id: test
      agent: testing.api-tester
      type: task
      depends_on: [prototype]
      side_effects:
        class: none
      on_fail: fix_and_retest

    - id: fix_and_retest
      agent: engineering.backend-architect
      type: task
      condition: "steps.test.status == 'failed'"
      inputs:
        failure_report: "{{steps.test.output.failure_details}}"
      side_effects:
        class: none
      on_success: test
      on_fail: escalate

  termination:
    stop_on:
      - policy_violation
      - budget_exceeded
    on_terminate: rollback
```

## 4.8 Rollback Classes

Rollback is not a single operation. Steps with different side-effect profiles require different rollback strategies.

| Side-Effect Class | Declared By | Rollback Behavior |
|-------------------|-------------|-------------------|
| `none` | Steps with no external effects | No rollback action needed. |
| `reversible` | Steps whose effects can be directly undone | Orchestrator invokes the step's undo operation (e.g., delete created resource). |
| `compensatable` | Steps whose effects can be offset by a compensation action | Orchestrator dispatches the declared `compensation_step`. |
| `irreversible` | Steps whose effects cannot be undone (e.g., sent email, external API call) | Log the irreversible effect. Escalate to human. No automatic rollback attempted. |

**On `on_terminate: rollback`**:

1. Orchestrator collects all completed steps in reverse execution order.
2. For each step:
   - `none` → skip
   - `reversible` → execute undo
   - `compensatable` → dispatch `compensation_step`
   - `irreversible` → log `workflow.rollback_skipped` event with reason, escalate
3. If any rollback step itself fails → log and escalate. Do not retry rollback steps.

**Rule**: Steps that invoke external write operations (API calls, file writes, deployments) MUST declare a `side_effects.class` other than `none`. The orchestrator parser flags undeclared external writes as a warning at parse time (best-effort static analysis) and the governor flags them as violations at runtime.

## 4.9 Agent-OS Mapping

| Orchestration Component | Agent-OS v1.0.0 Equivalent | Gap |
|---|---|---|
| Workflow parser | Not implemented | Full implementation needed |
| DAG resolver + fork ownership validation | Not implemented | Full implementation needed |
| Ready queue / dispatcher | Basic sequential execution exists | Needs parallel, conditional, retry support |
| Expression evaluator + null safety | Not implemented | Full implementation needed |
| Budget tracking in orchestrator | Not implemented | Needs governor integration |
| Side-effect tracking + rollback | Not implemented | Full implementation needed |

---

# Contract 5: Governance Lifecycle v1.1

## 5.1 Purpose

Define the three-phase governance model that controls agent execution from admission through completion. Governance is not a gate — it is a continuous authority that operates across the entire execution lifecycle.

## 5.2 Architecture

```
┌─────────────────────────────────────────────────────┐
│                 GOVERNANCE LIFECYCLE                  │
│                                                       │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐ │
│  │  ADMISSION    │→│   RUNTIME     │→│  COMPLETION  │ │
│  │  CONTROL      │  │   MONITOR     │  │  RECONCILER │ │
│  └──────────────┘  └───────────────┘  └────────────┘ │
│         │                  │                 │         │
│         ▼                  ▼                 ▼         │
│  Can this run?     Should this        Did it stay     │
│                    continue?          within limits?   │
└─────────────────────────────────────────────────────┘
```

## 5.3 Trust Model

Agent trust determines governance stringency. Trust is owned by governance, NOT by the agent spec, because trust is an operational assessment that changes independently of the agent's self-declared properties.

### Trust Registry

```json
{
  "trust_registry_version": "1.0.0",
  "entries": {
    "engineering.frontend-developer": {
      "trust_tier": "medium",
      "granted_by": "operator",
      "granted_at": "2026-03-18",
      "review_due": "2026-06-18",
      "notes": "Promoted from low after 50 successful tasks with no violations."
    },
    "testing.api-tester": {
      "trust_tier": "high",
      "granted_by": "operator",
      "granted_at": "2026-02-01",
      "review_due": "2026-05-01",
      "notes": "Read-only tool access, no external writes."
    }
  }
}
```

### Trust Tiers

| Tier | Meaning | Governance Behavior |
|------|---------|---------------------|
| `low` | New or untested agent | Strict admission checks, sandbox required, limited tools, tight budget ceilings |
| `medium` | Proven on routine tasks | Standard admission, sandbox recommended, standard tool access |
| `high` | Established track record | Relaxed admission for low/medium risk tasks, full tool access for approved tool set |
| `critical` | System-level agent (orchestrator, governor) | Auto-approve for operational tasks, but any anomaly triggers immediate review |

**Default**: Agents without a trust registry entry default to `low`.

**Promotion/demotion**: Operators manage trust manually. The completion reconciler can *recommend* trust changes based on performance metrics, but never applies them automatically.

## 5.4 Phase 1: Admission Control

**When**: Before any agent is dispatched.

**Checks**:

| Check | Input | Decision |
|-------|-------|----------|
| Budget ceiling | Task estimated cost vs. remaining budget | ALLOW / DENY |
| Tool permissions | Agent requested tools vs. allowed tools for task risk level and agent trust tier | ALLOW / DENY |
| Risk classification | Task risk level vs. agent trust tier (from trust registry) | ALLOW / DENY / REQUIRE_HUMAN_APPROVAL |
| Policy compliance | Task type + agent constraints vs. active policies (with precedence resolution) | ALLOW / DENY |
| Rate limiting | Agent invocation count in time window | ALLOW / THROTTLE / DENY |
| Dependency satisfaction | Required input availability | ALLOW / DEFER |

**Output**: `AdmissionDecision`

```json
{
  "decision": "allow | deny | defer | require_approval",
  "reason": "string",
  "conditions": {
    "max_tokens": 10000,
    "max_cost_usd": 0.25,
    "sandbox_required": true,
    "allowed_tools": ["code_editor", "linter"],
    "timeout_seconds": 120
  },
  "budget_reservation": {
    "amount_usd": 0.25,
    "state": "reserved",
    "expires_at": "ISO-8601"
  }
}
```

**Note**: `conditions` is a structured object (not a string array). All governance code accesses conditions as typed fields.

**Tool restriction rule**: Admission `conditions.allowed_tools` MUST be a subset of `agent.tools`. Governance may restrict but never expand the agent's declared tool set. If restriction reduces tools below what the agent requires for its `required_inputs` satisfaction, the admission decision MUST be `deny`, not `allow` with crippled tools.

### Budget Reservation Lifecycle

| State | Meaning | Transition |
|-------|---------|------------|
| `reserved` | Budget held for a task that has been admitted but not yet started | → `committed` on task start, → `released` on expiry/cancellation |
| `committed` | Task is actively executing; budget is in use | → `released` on completion (unused portion), → `released` on interruption |
| `released` | Unused budget returned to workflow pool | Terminal state |
| `expired` | Reservation timed out without task starting | → `released` automatically |

**Automatic release triggers**:
- `defer` timeout expires without task starting
- Router fails to dispatch after admission
- Orchestrator cancels task before dispatch
- Workflow terminates while reservation is active
- Reservation `expires_at` deadline passes

**Reservation expiry**: All reservations include an `expires_at` timestamp (default: 2x the step timeout). If a task has not transitioned to `committed` by expiry, the reservation is automatically released and a `governor.warning` event is emitted.

**Retry reservation semantics**: On step retry, the budget reservation lifecycle resets cleanly:

1. The completion reconciler releases the committed reservation (actual consumed → released, unused portion returned to workflow pool).
2. The retry triggers a NEW admission check with a NEW reservation.
3. The new reservation draws from the workflow's remaining budget (which now includes the released unused portion from the previous attempt).
4. If remaining budget is insufficient for a new reservation, admission denies the retry and the step fails with `budget_exceeded`.

Each retry attempt has exactly one reservation. No double-reservation, no carry-over.

## 5.5 Phase 2: Runtime Monitor

**When**: Continuously during agent execution.

**Monitors**:

| Monitor | Trigger | Action |
|---------|---------|--------|
| Token consumption | Exceeds 80% of step budget | WARN → log event |
| Token consumption | Exceeds 100% of step budget | INTERRUPT → force completion |
| Elapsed time | Exceeds step timeout | INTERRUPT → timeout failure |
| Tool invocation | Unauthorized tool call attempted | BLOCK → log violation |
| Output streaming | Detects policy-violating content pattern | INTERRUPT → escalate |
| Cost accumulation | Workflow cumulative cost exceeds 90% of budget | WARN all active steps |
| Cost accumulation | Workflow cumulative cost exceeds 100% | TERMINATE workflow |

**Implementation model**: The runtime monitor wraps agent execution. It does not poll — it intercepts the execution stream (token callbacks, tool call hooks, output handlers).

```python
class RuntimeMonitor:
    """Wraps agent execution with continuous governance."""

    def __init__(self, admission: AdmissionDecision, governor: Governor):
        self.admission = admission
        self.governor = governor
        self.tokens_consumed = 0
        self.cost_accumulated = 0.0
        self.start_time = time.monotonic()

    def on_token(self, token_count: int) -> MonitorAction:
        self.tokens_consumed += token_count
        if self.tokens_consumed > self.admission.conditions.max_tokens:
            return MonitorAction.INTERRUPT
        if self.tokens_consumed > self.admission.conditions.max_tokens * 0.8:
            self._emit_warning("token_budget_80_percent")
        return MonitorAction.CONTINUE

    def on_tool_call(self, tool_name: str) -> MonitorAction:
        if tool_name not in self.admission.conditions.allowed_tools:
            self._emit_violation("unauthorized_tool", tool_name)
            return MonitorAction.BLOCK
        return MonitorAction.CONTINUE

    def check_timeout(self) -> MonitorAction:
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.admission.conditions.timeout_seconds:
            return MonitorAction.INTERRUPT
        return MonitorAction.CONTINUE
```

## 5.6 Phase 3: Completion Reconciler

**When**: After agent execution completes (success or failure).

**Actions**:

| Action | Description |
|--------|-------------|
| Budget reconciliation | Compare reserved budget vs. actual cost. Transition reservation from `committed` to `released`. Return unused portion to workflow pool. |
| Output validation | Run evaluator chain against agent output. Validate against `output_schemas` if declared. Flag non-conformant output. |
| Metric recording | Write performance metrics to experience store: tokens, cost, duration, success/failure, failure classification. |
| Anomaly detection | Compare execution metrics against historical baselines. Classify anomalies by type. |
| Policy compliance audit | Verify no policy violations occurred during execution (check runtime monitor log). |
| Escalation check | If failure classification matches escalation criteria, notify human operator. |
| Trust recommendation | If performance consistently exceeds/underperforms expectations, recommend trust tier change to operator. |

### Anomaly Classes

| Class | Detection | Response |
|-------|-----------|----------|
| `latency_spike` | Duration > 2σ above mean for this agent + task type | Log + flag for review |
| `cost_spike` | Cost > 2σ above mean for this agent + task type | Log + flag for review |
| `retry_spike` | Retry count at max for 3+ consecutive tasks | Log + recommend investigation |
| `failure_cluster` | 3+ consecutive failures from same agent | Log + recommend suspension review |
| `tool_violation_pattern` | 2+ tool violations in a time window | Log + auto-restrict tools + escalate |
| `evaluator_failure_cluster` | 2+ evaluator execution failures in a time window | Log + flag evaluator for repair + escalate |

### Evaluator Failure Disposition

If an evaluator in the chain fails to execute (as opposed to returning a `passed: false` result):

1. Emit a `governor.warning` event with the evaluator class and error details.
2. The task output is marked `evaluation_incomplete` — not `passed` and not `failed`.
3. The reconciliation report includes the partial evaluation results and the failed evaluator.
4. The governor decides disposition based on risk tier:
   - **Low/medium risk**: accept output with `evaluation_incomplete` flag. Log for review.
   - **High/critical risk**: hold output. Escalate for human review or evaluator retry.
5. Evaluator failures are tracked in the experience store. Repeated evaluator failures trigger the `evaluator_failure_cluster` anomaly class.

**Output**: `ReconciliationReport`

```json
{
  "task_id": "uuid",
  "agent_id": "engineering.frontend-developer",
  "status": "completed | failed | interrupted | policy_violation | evaluation_incomplete",
  "budget": {
    "reserved": 0.25,
    "actual": 0.18,
    "released": 0.07,
    "reservation_state": "released"
  },
  "metrics": {
    "tokens_consumed": 8420,
    "duration_seconds": 34,
    "tool_calls": 3,
    "retries": 0
  },
  "evaluation_results": [
    { "evaluator": "schema", "passed": true },
    { "evaluator": "policy", "passed": true },
    { "evaluator": "quality_heuristic", "passed": true, "score": 0.87 }
  ],
  "anomalies": [],
  "trust_recommendation": null,
  "escalation_required": false
}
```

## 5.7 Risk Classification

Tasks and agents are classified into risk tiers that determine governance stringency:

| Tier | Examples | Admission | Monitoring | Reconciliation |
|------|----------|-----------|------------|----------------|
| **Low** | Read-only analysis, formatting, summarization | Auto-approve if budget available and trust >= low | Standard token/time monitoring | Standard metrics logging |
| **Medium** | Code generation, data transformation, API reads | Auto-approve with tool restrictions, trust >= medium | Full monitoring + tool call interception | Full evaluation chain |
| **High** | External API writes, file system modification, financial calculations | Requires trust >= high OR human approval | Real-time monitoring with tight thresholds | Full evaluation + mandatory human review of output |
| **Critical** | Production deployment, data deletion, security-sensitive operations | Always requires human approval regardless of trust | Continuous monitoring with immediate interrupt capability | Full evaluation + human sign-off before output is released |

## 5.8 Policy Registry and Precedence

Governance policies are stored as versioned, machine-readable rules:

```json
{
  "policy_id": "tool-access-control-v1",
  "version": "1.0.0",
  "priority": 100,
  "scope": "global | domain:<name> | agent:<id>",
  "rules": [
    {
      "condition": "agent.status == 'experimental'",
      "action": "restrict_tools_to",
      "value": ["code_editor", "linter"]
    },
    {
      "condition": "task.risk_tier == 'high'",
      "action": "require_sandbox",
      "value": true
    },
    {
      "condition": "task.risk_tier == 'critical'",
      "action": "require_human_approval",
      "value": true
    }
  ]
}
```

### Policy Precedence Rules

When multiple policies apply to the same admission decision:

| Rule | Behavior |
|------|----------|
| **Deny overrides allow** | If any applicable policy denies an action, the action is denied regardless of other policies that would allow it. |
| **Narrower scope wins** | `agent:<id>` policies override `domain:<name>` policies, which override `global` policies. |
| **Higher priority number wins** | Within the same scope level, policies with higher `priority` values take precedence. |
| **Explicit over default** | A policy that explicitly addresses a condition overrides the default behavior for that condition. |
| **Conflict resolution** | If two policies at the same scope and priority level produce contradictory results, the more restrictive outcome applies and a `governor.warning` event is emitted. |

**Effective policy resolution order**:
1. Collect all policies whose scope matches the current context
2. Sort by scope specificity (agent > domain > global), then by priority (descending)
3. Evaluate rules in order; first matching rule per action type wins
4. Apply deny-overrides-allow across all matched rules

## 5.9 Agent-OS Mapping

| Governance Component | Agent-OS v1.0.0 Equivalent | Gap |
|---|---|---|
| Trust registry | Not implemented | Full implementation needed |
| Admission control | Basic permission check exists | Needs budget reservation lifecycle, risk classification, policy engine |
| Runtime monitor | Not implemented (fire-and-forget execution) | Core gap — needs execution wrapper |
| Completion reconciler | Partial — basic logging exists | Needs budget reconciliation, anomaly classification, trust recommendations |
| Risk classification | Not implemented | Full implementation needed |
| Policy registry + precedence | Not implemented | Full implementation needed |
| Budget reservation lifecycle | Not implemented | Full implementation needed |

---

# Implementation Priority

Based on gap analysis across all five contracts:

| Priority | Component | Rationale |
|----------|-----------|-----------|
| **P0** | Agent Schema validation (with required/optional inputs) | Foundation — everything else depends on well-formed specs |
| **P0** | Registry with capability lookup + status filtering | Router cannot function without discovery |
| **P0** | Trust registry (simple JSON, operator-managed) | Governance references trust; must exist before admission control |
| **P1** | Router scoring engine (with routing modes) | Core dispatch logic; blocks all multi-agent work |
| **P1** | State Authority event log + projections + conflict classes | Replaces fragile shared state; blocks reliable orchestration |
| **P1** | AdmissionDecision with structured conditions + budget reservation | Enables governance pre-execution |
| **P2** | Orchestration parser + DAG resolver + fork ownership validation | Enables workflow definitions; depends on router + state |
| **P2** | Runtime monitor wrapper | Enables continuous governance during execution |
| **P2** | Expression evaluator with null safety | Enables conditional workflows |
| **P2** | Side-effect declarations + rollback class enforcement | Enables safe workflow termination |
| **P3** | Completion reconciler + anomaly classification | Enables feedback loop and experience store |
| **P3** | Full evaluator class hierarchy | Enables multi-mode output validation |
| **P3** | Policy registry + precedence engine | Enables complex multi-policy governance |
| **P3** | Output schema validation via `output_schemas` | Strengthens evaluator chain |

**Recommended implementation order**: P0 → P1 → P2 → P3, with each layer tested against Agent-OS v1.0.0 integration points before proceeding.

---

# Appendix A: Controlled Vocabulary (Starter Set)

## Capability Tags

```
build_ui, optimize_rendering, integrate_api, write_backend,
design_schema, analyze_data, synthesize_research, generate_report,
write_tests, review_code, debug_issue, deploy_service,
assess_risk, audit_compliance, monitor_security,
plan_sprint, prioritize_backlog, estimate_effort
```

## Failure Classifications

```
invalid_output_schema, policy_violation, budget_exceeded,
timeout, tool_failure, dependency_unavailable,
quality_below_threshold, unauthorized_action,
runtime_error, unrecoverable_error, expression_type_error,
compensation_failure, all_branches_denied, all_candidates_denied
```

## Event Types

```
task.created, task.routed, task.started, task.completed,
task.failed, task.retried, task.skipped,
agent.output, context.updated,
governor.decision, governor.warning, governor.violation,
workflow.started, workflow.completed, workflow.terminated,
workflow.rollback_skipped,
monitor.warning, monitor.interrupt,
budget.reserved, budget.committed, budget.released, budget.expired,
trust.recommendation
```

## Context Conflict Classes

```
replaceable, mergeable, exclusive, append_only
```

## Anomaly Classes

```
latency_spike, cost_spike, retry_spike,
failure_cluster, tool_violation_pattern,
evaluator_failure_cluster
```

## Trust Tiers

```
low, medium, high, critical
```

## Budget Reservation States

```
reserved, committed, released, expired
```

## Side-Effect Classes

```
none, reversible, compensatable, irreversible
```

## Routing Modes

```
single, ranked, ensemble, manual_review
```

---

# Appendix B: Changelog v1.0 → v1.1

| # | Correction | Contract | Section |
|---|-----------|----------|---------|
| 1 | `AdmissionDecision.conditions` changed from string array to structured object | 5 | §5.4 |
| 2 | Agent `inputs` split into `required_inputs` and `optional_inputs`; router filters on required only | 1, 2 | §1.2, §2.3 |
| 3 | Trust model added as governance-owned registry, not agent self-declaration | 5 | §5.3 |
| 4 | Default last-event-wins replaced with typed conflict classes (`replaceable`, `mergeable`, `exclusive`, `append_only`) | 3 | §3.4 |
| 5 | Fork semantics clarified: fork references existing step IDs, does not define inline. Ownership rules added. | 4 | §4.3 |
| 6 | SemVer rules refined: major/minor/patch mapped to specific field change classes | 1 | §1.4 |
| 7 | Excess capability penalty removed; replaced with specialization bonus (overlap ratio > 0.7) | 2 | §2.3 |
| 8 | Expression language null-safety and missing-field semantics defined | 4 | §4.5 |
| 9 | Budget reservation lifecycle added with states: reserved/committed/released/expired | 5 | §5.4 |
| 10 | Rollback classes defined: none/reversible/compensatable/irreversible with per-step declaration | 4 | §4.8 |
| 11 | Write scope expanded to event-type + namespace granularity; context namespaces defined | 3 | §3.5 |
| 12 | Policy precedence rules added: deny-overrides-allow, scope specificity, priority number | 5 | §5.8 |
| A1 | `output_schemas` field added to agent spec for evaluator-bindable output validation | 1 | §1.2 |
| A2 | `routing_mode` field added to task descriptor (single/ranked/ensemble/manual_review) | 2 | §2.2 |
| A3 | `idempotency_key` field added to event schema for safe retries | 3 | §3.3 |
| A4 | `side_effects` declaration added to orchestration step schema | 4 | §4.2, §4.8 |
| A5 | Anomaly classes defined and typed | 5 | §5.6 |
| A6 | `expression_type_error` added to failure classifications | Appendix | §A |

---

# Appendix C: Changelog v1.1 → v1.2

All items below are from the v1.1 net-new gap audit (Section A of Conformance & Integration Matrix). Items marked P1-blocking were required before router/orchestrator implementation.

| # | Fix | Contract | Section | Priority |
|---|-----|----------|---------|----------|
| A1.1 | Output schema validation timing made explicit: registry validates at registration, not evaluation time | 1 | §1.3 | P1-blocking |
| A1.2 | Orchestrator must populate `inputs_available` from completed predecessor outputs before dispatching to router | 4 | §4.6 | P1-blocking |
| A1.3 | `conditions.allowed_tools` must be subset of `agent.tools`; governance restricts but never expands | 5 | §5.4 | P1-blocking |
| A1.4 | Budget lifecycle events (`budget.reserved/committed/released/expired`) and `trust.recommendation` added to canonical event types | 3 | §3.3 | P1-blocking |
| A2.1 | Retry budget reservation semantics: release-and-re-reserve per attempt, no double-reservation | 5 | §5.4 | P1-blocking |
| A2.3 | Fork partial admission: proceed with admitted branches, skip denied, fail if all denied. Join resolves on any terminal state. | 4 | §4.3 | P1-blocking |
| A3.1 | Advisory vs authoritative admission: router filter is point-in-time; orchestrator re-checks at dispatch; fallback chain on denial | 2 | §2.5 | P1-blocking |
| A3.2 | Join terminal state resolution: branches resolved on completed/failed/skipped/interrupted; non-completed outputs absent from merge | 4 | §4.3 | P1-blocking |
| A3.4 | Evaluator failure disposition: `evaluation_incomplete` status, risk-tiered handling, `evaluator_failure_cluster` anomaly class | 5 | §5.6 | P1-blocking |
| V1 | `compensation_failure`, `all_branches_denied`, `all_candidates_denied` added to failure classifications | Appendix | §A | Vocabulary |
| V2 | `evaluator_failure_cluster` added to anomaly classes | Appendix | §A | Vocabulary |
| V3 | Budget and trust event types added to canonical event type list | Appendix | §A | Vocabulary |
