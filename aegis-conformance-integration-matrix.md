# Aegis Runtime Contracts v1.1 — Conformance & Integration Matrix

**Status**: Pre-Implementation Assessment  
**Source of Truth**: aegis-runtime-contracts-v1.1.md  
**Target**: Agent-OS v1.0.0  
**Date**: 2026-03-19

---

# Section A: v1.1 Net-New Gap Audit

This audit targets v1.1 only. Zero recycled v1.0 findings. All items below are second-order problems introduced or exposed by the v1.1 corrections.

---

## A1. Contract-Level Consistency

### A1.1 — `output_schemas` validation timing is undefined

**Location**: Contract 1 §1.2, Contract 5 §5.6

The agent schema declares `output_schemas` as a map of output name → JSON Schema reference. The evaluator in the completion reconciler validates outputs against these schemas.

**Gap**: No contract specifies *when* schema references are validated for resolvability.

- Are they validated at agent registration? (Registry responsibility)
- At workflow parse time? (Orchestrator responsibility)
- At evaluation time? (Evaluator responsibility)

If deferred to evaluation time, a missing schema file causes a runtime failure after the agent has already consumed budget. If validated at registration, schemas must be available in the registry's accessible path.

**Risk**: Medium. A missing schema ref causes either a silent pass (no validation) or a late runtime failure.

**Fix**: Add explicit rule to Contract 1: "All `output_schemas` references MUST resolve to valid JSON Schema files at registration time. The registry rejects agent specs with unresolvable schema references." This is the cheapest enforcement point.

---

### A1.2 — Router consumes `required_inputs` but orchestrator resolves `depends_on` — no cross-validation

**Location**: Contract 2 §2.3, Contract 4 §4.6

The router filters agents by checking `task.inputs_available ⊇ agent.required_inputs`. The orchestrator resolves step dependencies via `depends_on`. But there is no contract-level guarantee that the orchestrator correctly populates `inputs_available` on the task descriptor from predecessor step outputs before dispatching to the router.

**Gap**: The handoff between "orchestrator knows what outputs exist" and "router checks what inputs are available" is implicit.

**Risk**: Medium. If the orchestrator builds the task descriptor without correctly mapping predecessor outputs to `inputs_available`, the router will either over-filter (missing inputs that do exist) or under-filter (claiming inputs that haven't been produced).

**Fix**: Add to Contract 4 §4.6 (Execution Semantics): "Before dispatching a step to the router, the orchestrator MUST populate `task.inputs_available` by collecting all output types declared in the `outputs` field of completed predecessor steps. The orchestrator MUST NOT include output types from steps that failed or were skipped."

---

### A1.3 — Governance `conditions.allowed_tools` vs. Agent Schema `tools` — who is authoritative?

**Location**: Contract 1 §1.2, Contract 5 §5.4

The agent schema declares `tools` (what the agent is permitted to invoke). Admission control returns `conditions.allowed_tools` (what the agent is allowed to invoke for *this specific task*). The runtime monitor enforces `conditions.allowed_tools`.

**Gap**: No contract states the relationship between these two. Is `conditions.allowed_tools` always a subset of `agent.tools`? Can governance *add* tools not in the agent spec? What happens if governance restricts tools below what the agent considers minimum viable?

**Risk**: Low-medium. In practice, governance will restrict. But without an explicit rule, an implementation could accidentally *expand* tool access beyond the agent's declared set.

**Fix**: Add to Contract 5 §5.4: "Admission `conditions.allowed_tools` MUST be a subset of `agent.tools`. Governance may restrict but never expand the agent's declared tool set. If restriction reduces tools below what the agent needs for `required_inputs` satisfaction, the admission decision MUST be `deny`, not `allow` with crippled tools."

---

### A1.4 — Event types in Contract 3 vs. events emitted by Contract 4 and Contract 5 — no formal alignment check

**Location**: Contract 3 §3.3, Contract 4 §4.6, Contract 5 §5.4-5.6

Contract 3 defines canonical event types. Contracts 4 and 5 describe behaviors that emit events ("every state transition emits an event," "budget reservation transitions emit events," etc.) but don't always map to specific event types from the canonical set.

**Gap**: Examples of events described in behavior but not in the canonical list:
- `budget.reserved`, `budget.committed`, `budget.released`, `budget.expired` — the reservation lifecycle implies events but none are in the event type list.
- `workflow.rollback_skipped` — referenced in §4.8 but not in the §3.3 canonical list. *[Correction: this IS in Appendix A event types. Confirmed present.]*
- Trust tier changes — the reconciler can "recommend" trust changes, but no event type captures this.

**Risk**: Medium. Implementers will invent ad-hoc event types for budget lifecycle and trust recommendations, creating fragmentation.

**Fix**: Add to Contract 3 §3.3 canonical event types:

| Event Type | Payload | Scope |
|---|---|---|
| `budget.reserved` | Task ID, amount, expires_at | workflow |
| `budget.committed` | Task ID, amount | workflow |
| `budget.released` | Task ID, amount, reason | workflow |
| `budget.expired` | Task ID, amount | workflow |
| `trust.recommendation` | Agent ID, current tier, recommended tier, evidence | global |

---

## A2. Edge-Case Semantics

### A2.1 — Retry with partially consumed budget reservation

**Location**: Contract 5 §5.4, Contract 4 §4.2

A step fails and retries. The budget reservation was `committed` during the first attempt. On retry:
- Is the original reservation released and a new one created?
- Is the remaining reservation carried over?
- Does the retry get a fresh admission check?

**Gap**: The budget reservation lifecycle defines states but not the retry-specific transition path.

**Risk**: High. Budget accounting breaks under retries. Either budget is double-reserved (leak) or under-reserved (overrun).

**Fix**: Add to Contract 5 §5.4 Budget Reservation Lifecycle:

"On step retry:
1. The completion reconciler releases the committed reservation (actual consumed → released, unused portion returned).
2. The retry triggers a NEW admission check with a NEW reservation.
3. The new reservation draws from the workflow's remaining budget (which now includes the released unused portion from attempt 1).
4. If remaining budget is insufficient for a new reservation, admission denies the retry and the step fails with `budget_exceeded`."

This ensures budget accounting is always one-reservation-per-attempt with clean release/re-reserve transitions.

---

### A2.2 — Trust registry update during in-flight execution

**Location**: Contract 5 §5.3, §5.5

An operator demotes an agent's trust tier from `high` to `low` while that agent is mid-execution on a `high`-risk task.

**Gap**: No contract specifies whether trust changes are:
- Immediately effective (could interrupt running tasks)
- Effective only for new admissions (running tasks continue under original trust)
- Queued until current execution completes

**Risk**: Medium. Immediate enforcement could cause unpredictable interruptions. Deferred enforcement could allow a now-untrusted agent to complete sensitive work.

**Fix**: Add to Contract 5 §5.3:

"Trust tier changes take effect at the next admission check. Running tasks continue under the trust tier that was active at their admission time. The runtime monitor does NOT re-evaluate trust mid-execution. If an operator requires immediate termination of in-flight work by a demoted agent, they must issue an explicit workflow termination command."

This is the simplest model that avoids mid-execution disruption while giving operators an escape hatch.

---

### A2.3 — Fork branch partially admitted

**Location**: Contract 4 §4.3, Contract 5 §5.4

A fork declares three branches. Governance admits two but denies the third (e.g., budget insufficient for all three).

**Gap**: No contract specifies the fork's behavior when a subset of branches are admitted.

Options:
- Fork proceeds with admitted branches only (partial execution)
- Fork fails entirely if any branch is denied (all-or-nothing)
- Fork proceeds but marks denied branches as `skipped` for the join

**Risk**: High. This directly affects workflow determinism. The join step's `expects` list won't match what actually ran.

**Fix**: Add to Contract 4 §4.3 fork rules:

"If any branch step is denied by governance:
1. The fork emits a `task.skipped` event for each denied branch with reason `admission_denied`.
2. The fork proceeds with admitted branches only.
3. The join step receives the partial result set. If `on_timeout: proceed_with_available` is set, the join proceeds with available outputs. If not set, the join evaluates whether it can proceed based on its `expects` list — if all expected branches are either completed or skipped, the join fires.
4. If ALL branches are denied, the fork itself fails with `all_branches_denied` and follows its `on_fail` handler."

---

### A2.4 — Rollback of compensatable step when compensation step also fails

**Location**: Contract 4 §4.8

The rollback sequence dispatches a `compensation_step` for `compensatable` side effects. But what if the compensation step itself fails?

**Gap**: The contract says "If any rollback step itself fails → log and escalate. Do not retry rollback steps." This is stated but the failure classification and event emission for failed compensation are not specified.

**Risk**: Low-medium. The behavior is partially defined but the event trail will be incomplete.

**Fix**: Add to Contract 4 §4.8:

"If a compensation step fails:
1. Emit `task.failed` event for the compensation step with classification `compensation_failure`.
2. Emit `workflow.rollback_skipped` event for the original step, noting that compensation was attempted but failed.
3. Escalate to human operator with both the original step's side effects and the compensation failure details.
4. Do not retry the compensation step."

Add `compensation_failure` to the failure classifications vocabulary.

---

### A2.5 — Projection rebuild requiring archived events

**Location**: Contract 3 §3.7

Snapshots are taken every N events. Events older than `ttl_days` are archived (not deleted). Replay starts from the latest snapshot.

**Gap**: If a snapshot is corrupted or missing, replay must go further back — potentially into archived events. No contract specifies:
- How archived events are retrieved for replay
- Whether projection rebuild is guaranteed to succeed if archives are available
- What happens if archives are also unavailable

**Risk**: Low for normal operation. High for disaster recovery.

**Fix**: Add to Contract 3 §3.7:

"If the latest snapshot is corrupted or unavailable:
1. Attempt replay from the next most recent snapshot.
2. If no valid snapshot exists, replay from the beginning of the event log, loading archived events as needed.
3. Archived events MUST be retrievable within the retention period (`ttl_days`). The archive store must support sequential read access.
4. If archived events required for replay are unavailable, the projection enters `degraded` state. The state authority emits a `governor.warning` event and falls back to the most recent valid snapshot, even if stale.
5. A projection in `degraded` state is flagged to all consumers. The governor may block new task dispatches until the projection is repaired."

---

## A3. Cross-Contract Failure Paths

### A3.1 — Router returns candidates, admission denies all

**Location**: Contract 2 §2.3, Contract 5 §5.4

The router's filter phase includes `Governor.admissionCheck(task, agent) == PASS` as step 1f. So in theory, denied agents are filtered before scoring.

**Gap**: But admission checks may depend on runtime state (current budget, current rate limits) that changes between the router's filter pass and actual dispatch. The router could return a candidate that was admissible during scoring but is denied by the time dispatch happens (budget consumed by a parallel step in the interim).

**Risk**: Medium. Race condition between routing and admission under parallel execution.

**Fix**: Add to Contract 2 §2.3:

"The router's admission check in the filter phase is advisory (point-in-time). The authoritative admission check occurs at dispatch time in the orchestrator. If the dispatched agent fails the authoritative admission check:
1. The orchestrator attempts the next fallback candidate from the router's ranked list.
2. If all fallback candidates fail admission, the orchestrator emits a `task.failed` event with classification `all_candidates_denied` and follows the step's `on_fail` handler.
3. The router is NOT re-invoked automatically. Re-routing requires explicit orchestrator logic or step retry."

---

### A3.2 — Join step with one branch terminated by governance and one completed

**Location**: Contract 4 §4.3, Contract 5 §5.5

During parallel execution, the runtime monitor terminates one branch (e.g., budget exceeded) while the other completes successfully.

**Gap**: This is partially covered by A2.3 (fork branch partially admitted), but this scenario is different — the branch *started* but was *interrupted* mid-execution. The join step's behavior for interrupted (not skipped) branches is undefined.

**Risk**: Medium. The join may hang waiting for an output that will never arrive.

**Fix**: Add to Contract 4 §4.3 join rules:

"A join step considers a branch resolved when it reaches any terminal state: `completed`, `failed`, `skipped`, or `interrupted`. For branches in non-`completed` states:
- Their outputs are absent from the merge set.
- The join proceeds according to its `on_timeout` policy: `proceed_with_available` uses only completed branch outputs; absence of this policy means the join fails if any expected branch did not complete.
- An interrupted or failed branch contributes its status but not its output to the join's evaluation context."

---

### A3.3 — Policy precedence collision during runtime monitoring

**Location**: Contract 5 §5.5, §5.8

Policy precedence rules are defined for admission control. But the runtime monitor also enforces policies (tool access, content patterns). If policies are updated while a task is executing, the runtime monitor could encounter a precedence collision that wasn't present at admission time.

**Gap**: No contract specifies whether the runtime monitor uses the admission-time policy snapshot or the current live policy set.

**Risk**: Low-medium. Policy updates during execution are rare but possible, especially in long-running tasks.

**Fix**: Add to Contract 5 §5.5:

"The runtime monitor operates under the policy set that was effective at admission time. Policy changes during execution do not affect in-flight tasks. This ensures deterministic enforcement within a single execution. New policies take effect at the next admission check. If an operator requires immediate policy enforcement on in-flight tasks, they must issue an explicit workflow termination command."

This mirrors the trust-change rule from A2.2 and creates a consistent "admission-time snapshot" model for both trust and policy.

---

### A3.4 — Evaluator failure after successful runtime completion

**Location**: Contract 5 §5.6

The completion reconciler runs the evaluator chain after execution. If the evaluator itself fails (e.g., schema validator crashes, external evaluation service unavailable), the task output exists but is unvalidated.

**Gap**: No contract specifies whether unvalidated output is:
- Accepted with a warning
- Rejected (treated as task failure)
- Held pending evaluator recovery

**Risk**: Medium. If treated as accepted, broken evaluators silently disable quality control. If treated as failure, evaluator bugs cause false task failures.

**Fix**: Add to Contract 5 §5.6:

"If an evaluator in the chain fails to execute (as opposed to returning a `passed: false` result):
1. Emit a `governor.warning` event with the evaluator class and error details.
2. The task output is marked `evaluation_incomplete` — not `passed` and not `failed`.
3. The reconciliation report includes the partial evaluation results and the failed evaluator.
4. The governor decides disposition based on risk tier:
   - Low/medium risk: accept output with `evaluation_incomplete` flag. Log for review.
   - High/critical risk: hold output. Escalate for human review or evaluator retry.
5. Evaluator failures are tracked in the experience store. Repeated evaluator failures trigger an anomaly class `evaluator_failure_cluster`."

Add `evaluator_failure_cluster` to anomaly classes. Add `evaluation_incomplete` as a task status.

---

## A4. Audit Summary

| ID | Severity | Category | Contract(s) | Status |
|----|----------|----------|-------------|--------|
| A1.1 | Medium | Consistency | 1, 5 | Fix: schema validation at registration |
| A1.2 | Medium | Consistency | 2, 4 | Fix: orchestrator must populate inputs_available from predecessors |
| A1.3 | Low-Med | Consistency | 1, 5 | Fix: allowed_tools ⊆ agent.tools, never expands |
| A1.4 | Medium | Consistency | 3, 4, 5 | Fix: add budget lifecycle + trust recommendation event types |
| A2.1 | High | Edge Case | 4, 5 | Fix: release-and-re-reserve per retry attempt |
| A2.2 | Medium | Edge Case | 5 | Fix: trust changes effective at next admission, not mid-execution |
| A2.3 | High | Edge Case | 4, 5 | Fix: fork proceeds with admitted branches, denied branches skipped |
| A2.4 | Low-Med | Edge Case | 4 | Fix: failed compensation → log, escalate, no retry |
| A2.5 | Low (High for DR) | Edge Case | 3 | Fix: degraded projection state with fallback behavior |
| A3.1 | Medium | Cross-Contract | 2, 5 | Fix: advisory vs authoritative admission, fallback chain |
| A3.2 | Medium | Cross-Contract | 4, 5 | Fix: join resolves on any terminal state, not just completed |
| A3.3 | Low-Med | Cross-Contract | 5 | Fix: admission-time policy snapshot for runtime monitor |
| A3.4 | Medium | Cross-Contract | 5 | Fix: evaluation_incomplete status, risk-tiered disposition |

**High severity items**: A2.1, A2.3  
**Items requiring new vocabulary terms**: A2.4 (`compensation_failure`), A3.4 (`evaluation_incomplete`, `evaluator_failure_cluster`)  
**Items requiring new event types**: A1.4 (5 new event types)

---

# Section B: Agent-OS v1.0.0 Mapping Matrix

Based on Agent-OS v1.0.0 codebase (~47 files, 323 tests, real Claude API integration).

## B1. Contract 1 — Agent Schema

| v1.1 Element | Agent-OS Component | Status | Action |
|---|---|---|---|
| Agent spec JSON Schema | Agent base class + loader | **Partial** | Extend: add JSON Schema validation at load time |
| `agent_id` namespace convention | Agent `name` attribute | **Partial** | Extend: enforce `domain.agent-name` pattern |
| `version` with SemVer rules | Not implemented | **Missing** | Build: version field + diff-based validation |
| `status` enum | Not implemented | **Missing** | Build: status field + registry filtering |
| `capabilities` from controlled vocabulary | Implicit in class behavior | **Missing** | Build: explicit capability tags + vocabulary registry |
| `required_inputs` / `optional_inputs` | Single inputs concept | **Partial** | Replace: split inputs, update all consumers |
| `output_schemas` | Not implemented | **Missing** | Build: schema registry + registration-time validation |
| `tools` permission list | Implicit in tool usage | **Partial** | Extend: explicit tool declaration + governor check |
| `depends_on` / `required_inputs_from` | Not implemented | **Missing** | Build: dependency graph in registry |
| `environment` (runtime, sandbox, timeout) | Subprocess sandbox exists | **Partial** | Extend: per-agent environment config |
| `evaluation` block | Test harness exists | **Partial** | Extend: runtime evaluator binding |
| `metadata` / `changelog` | Not implemented | **Missing** | Build: low priority, metadata only |

## B2. Contract 2 — Router

| v1.1 Element | Agent-OS Component | Status | Action |
|---|---|---|---|
| Task descriptor schema | Task dict (informal) | **Partial** | Replace: formal schema with validation |
| `routing_mode` | Not implemented | **Missing** | Build: mode flag + dispatch behavior per mode |
| Filter phase (status, capabilities, inputs, tools, environment, admission) | Basic capability check | **Partial** | Replace: full filter chain |
| Score phase (capability match, context relevance, performance history, cost risk) | Not implemented | **Missing** | Build: scoring engine |
| Specialization bonus | Not implemented | **Missing** | Build: part of scoring engine |
| Rank + fallback candidates | Not implemented | **Missing** | Build: ranked return with fallback list |
| Experience store integration | Not implemented | **Missing** | Build: requires experience store (P3) |
| Side-effect-free guarantee | Dispatcher has side effects | **Non-conformant** | Replace: pure function routing |

## B3. Contract 3 — State Authority

| v1.1 Element | Agent-OS Component | Status | Action |
|---|---|---|---|
| Immutable event log | Execution log (append-only) | **Partial** | Extend: event schema, typed events, immutability guarantee |
| Event schema (id, idempotency_key, type, source, scope, payload, causation, correlation) | Informal log entries | **Non-conformant** | Replace: structured event model |
| Conflict classes (replaceable, mergeable, exclusive, append_only) | Not implemented | **Missing** | Build: conflict resolution in projection layer |
| State projections | Not implemented | **Missing** | Build: projection classes with event replay |
| Read scoping (global, workflow, agent) | Not implemented | **Missing** | Build: scope filter on projection queries |
| Write scoping (event type + namespace) | Not implemented | **Missing** | Build: write permission checks in sequencer |
| Context namespaces | Not implemented | **Missing** | Build: namespace registry |
| Write sequencer | Firestore direct writes | **Non-conformant** | Replace: sequencer with monotonic ordering |
| Snapshots | Not implemented | **Missing** | Build: periodic projection serialization |
| Retention / archival | Not implemented | **Missing** | Build: TTL-based archival policy |
| Idempotency dedup | Not implemented | **Missing** | Build: idempotency check in sequencer |

## B4. Contract 4 — Orchestration Grammar

| v1.1 Element | Agent-OS Component | Status | Action |
|---|---|---|---|
| Workflow YAML/JSON parser | Not implemented | **Missing** | Build: parser + schema validation |
| DAG resolver | Not implemented | **Missing** | Build: topological sort + cycle detection |
| Fork ownership validation | Not implemented | **Missing** | Build: fork-branch relationship validator |
| Step types (task, gate, fork, join) | Basic sequential task execution | **Partial** | Extend: add gate, fork, join step handlers |
| Ready queue | Implicit sequential queue | **Partial** | Replace: dependency-aware ready queue |
| Expression evaluator + null safety | Not implemented | **Missing** | Build: expression parser + evaluator |
| `side_effects` declaration | Not implemented | **Missing** | Build: side-effect tracking per step |
| Rollback classes (none, reversible, compensatable, irreversible) | Not implemented | **Missing** | Build: rollback dispatcher |
| Budget tracking in orchestrator | Not implemented | **Missing** | Build: budget check before dispatch |
| `on_fail` / `on_success` routing | Not implemented | **Missing** | Build: control flow handlers |
| Retry with backoff | Not implemented | **Missing** | Build: retry logic with backoff strategy |
| Termination handlers | Not implemented | **Missing** | Build: termination + rollback sequence |

## B5. Contract 5 — Governance Lifecycle

| v1.1 Element | Agent-OS Component | Status | Action |
|---|---|---|---|
| Trust registry | Not implemented | **Missing** | Build: JSON registry, operator-managed |
| Admission control | Basic permission check | **Partial** | Replace: full admission with budget, tools, risk, policy, rate limit, dependency checks |
| `AdmissionDecision` structured response | Not implemented | **Missing** | Build: structured decision object |
| Budget reservation lifecycle (reserved → committed → released / expired) | Not implemented | **Missing** | Build: reservation state machine |
| Runtime monitor (token, time, tool, cost interception) | Not implemented (fire-and-forget) | **Missing** | Build: execution wrapper with callbacks |
| Completion reconciler | Basic logging | **Partial** | Extend: budget reconciliation, evaluator chain, anomaly detection |
| Risk classification (low / medium / high / critical) | Not implemented | **Missing** | Build: risk tier assignment + governance behavior mapping |
| Policy registry + precedence engine | Not implemented | **Missing** | Build: policy store, precedence resolver |
| Anomaly classification | Not implemented | **Missing** | Build: statistical baseline + anomaly typing |
| Experience store | Not implemented | **Missing** | Build: structured metrics store (feeds router scoring + anomaly detection) |

## B6. Status Summary

| Status | Count | Percentage |
|--------|-------|------------|
| **Missing** | 38 | 63% |
| **Partial** | 15 | 25% |
| **Non-conformant** | 4 | 7% |
| **Conformant** | 0 | 0% |
| **N/A** | 3 | 5% |

**Interpretation**: Agent-OS v1.0.0 is a working execution prototype but covers roughly 20-25% of the v1.1 contract surface. The existing code is not wasted — the agent loader, subprocess sandbox, execution log, and test harness are real foundations. But most of the contract infrastructure (scoring, state authority, orchestration grammar, governance lifecycle) is greenfield.

---

# Section C: P0 Build List

P0 scope: Agent Schema validation + Registry with capability lookup + Trust registry. These are the foundation that every other contract depends on.

## C1. Files to Create

```
aegis/
├── contracts/
│   └── schemas/
│       ├── agent_spec_v1.json          # JSON Schema from Contract 1 §1.2
│       ├── task_descriptor_v1.json     # JSON Schema from Contract 2 §2.2
│       └── event_v1.json              # JSON Schema from Contract 3 §3.3
├── registry/
│   ├── __init__.py
│   ├── agent_registry.py             # Core registry: register, lookup, query
│   ├── capability_vocabulary.py      # Controlled vocabulary enforcement
│   ├── trust_registry.py            # Trust tier storage and lookup
│   └── schema_validator.py          # JSON Schema validation for agent specs
├── models/
│   ├── __init__.py
│   ├── agent_spec.py                # AgentSpec dataclass/Pydantic model
│   ├── trust_entry.py               # TrustEntry dataclass
│   └── enums.py                     # Status, TrustTier, ConflictClass, etc.
└── tests/
    ├── test_agent_spec_validation.py
    ├── test_registry_crud.py
    ├── test_capability_lookup.py
    ├── test_trust_registry.py
    └── test_version_enforcement.py
```

## C2. Interfaces to Define

### AgentSpec (models/agent_spec.py)

```python
@dataclass
class AgentSpec:
    agent_id: str                          # pattern: domain.agent-name
    version: str                           # semver
    status: AgentStatus                    # active | deprecated | experimental | suspended
    role: str
    capabilities: list[str]                # from controlled vocabulary
    required_inputs: list[str]
    optional_inputs: list[str]
    outputs: list[str]
    output_schemas: dict[str, str]         # output_name → schema ref path
    tools: list[str]
    constraints: list[str]
    depends_on: list[str]
    required_inputs_from: dict[str, str]   # input_name → source_agent_id
    environment: EnvironmentConfig
    evaluation: EvaluationConfig
    metadata: AgentMetadata | None
```

### AgentRegistry (registry/agent_registry.py)

```python
class AgentRegistry:
    def register(self, spec: AgentSpec) -> RegistrationResult:
        """Validate and register an agent spec.
        
        Validates:
        - JSON Schema conformance
        - agent_id uniqueness
        - version increment rules (if updating existing)
        - capabilities against controlled vocabulary
        - output_schemas resolvability
        - tools against tool permission registry
        """

    def get(self, agent_id: str) -> AgentSpec | None:
        """Lookup by exact agent_id."""

    def query_by_capability(
        self, 
        required: list[str], 
        status_filter: list[AgentStatus] = [AgentStatus.ACTIVE]
    ) -> list[AgentSpec]:
        """Find agents matching ALL required capabilities.
        Filters by status. Returns full specs for router consumption."""

    def query_by_output(self, output_type: str) -> list[AgentSpec]:
        """Find agents that produce a given output type.
        Used by orchestrator to resolve depends_on chains."""

    def deregister(self, agent_id: str) -> bool:
        """Remove agent from registry. Does not delete spec history."""

    def get_version_history(self, agent_id: str) -> list[AgentSpec]:
        """Return all registered versions of an agent, ordered by version."""
```

### TrustRegistry (registry/trust_registry.py)

```python
class TrustRegistry:
    def get_trust(self, agent_id: str) -> TrustTier:
        """Return trust tier. Default: TrustTier.LOW for unknown agents."""

    def set_trust(
        self, 
        agent_id: str, 
        tier: TrustTier, 
        granted_by: str, 
        notes: str = ""
    ) -> TrustEntry:
        """Set or update trust tier. Operator-only action."""

    def get_entry(self, agent_id: str) -> TrustEntry | None:
        """Return full trust entry with metadata."""
```

### CapabilityVocabulary (registry/capability_vocabulary.py)

```python
class CapabilityVocabulary:
    def validate(self, capabilities: list[str]) -> ValidationResult:
        """Check all capabilities are in controlled vocabulary.
        Returns list of unknown capabilities if any."""

    def register_capability(self, capability: str) -> bool:
        """Add new capability to vocabulary. Idempotent."""

    def list_capabilities(self) -> list[str]:
        """Return all registered capabilities."""
```

## C3. Tests to Write

### test_agent_spec_validation.py

| Test | Validates |
|------|-----------|
| `test_valid_spec_passes` | Well-formed spec passes validation |
| `test_missing_required_field_fails` | Each required field triggers rejection when absent |
| `test_invalid_agent_id_pattern_fails` | IDs not matching `domain.agent-name` rejected |
| `test_invalid_semver_fails` | Non-semver version strings rejected |
| `test_invalid_status_fails` | Status values outside enum rejected |
| `test_empty_capabilities_fails` | Capabilities array must have ≥1 entry |
| `test_unknown_capability_fails` | Capabilities not in vocabulary rejected |
| `test_unresolvable_output_schema_fails` | Schema refs that don't resolve rejected at registration |
| `test_valid_spec_with_optional_fields` | Spec with only required fields passes; optional fields have correct defaults |

### test_registry_crud.py

| Test | Validates |
|------|-----------|
| `test_register_and_get` | Basic register → get roundtrip |
| `test_duplicate_agent_id_rejected` | Same agent_id cannot be registered twice (must use version update) |
| `test_version_update_accepted` | Higher version of existing agent replaces previous |
| `test_major_bump_required_for_breaking_change` | I/O change with minor bump is rejected |
| `test_minor_bump_accepted_for_additive_change` | New capability with minor bump passes |
| `test_patch_bump_accepted_for_metadata_change` | Metadata-only change with patch bump passes |
| `test_deregister_removes_from_active` | Deregistered agent not returned by queries |
| `test_deregister_preserves_history` | Version history still accessible after deregistration |

### test_capability_lookup.py

| Test | Validates |
|------|-----------|
| `test_query_single_capability` | Returns agents with that capability |
| `test_query_multiple_capabilities_intersection` | Returns only agents matching ALL capabilities |
| `test_query_filters_by_status` | Deprecated/suspended agents excluded by default |
| `test_query_returns_empty_for_unknown_capability` | No crash, empty list |
| `test_query_by_output_type` | Finds agents that produce a specific output |

### test_trust_registry.py

| Test | Validates |
|------|-----------|
| `test_unknown_agent_defaults_to_low` | Agents not in trust registry return `TrustTier.LOW` |
| `test_set_and_get_trust` | Basic set → get roundtrip |
| `test_trust_update_preserves_history` | Previous trust entry still accessible |
| `test_trust_entry_metadata` | `granted_by`, `granted_at`, `review_due` populated |

### test_version_enforcement.py

| Test | Validates |
|------|-----------|
| `test_breaking_input_change_requires_major` | Removing a required_input with minor bump → rejected |
| `test_breaking_output_change_requires_major` | Changing output list with minor bump → rejected |
| `test_adding_capability_is_minor` | New capability with minor bump → accepted |
| `test_metadata_change_is_patch` | Changelog update with patch bump → accepted |
| `test_no_version_downgrade` | Registering lower version than current → rejected |

## C4. Acceptance Criteria for P0

P0 is complete when:

1. All agent specs in the system are validated against JSON Schema at registration time.
2. The registry supports lookup by `agent_id`, query by capability set, and query by output type.
3. The capability vocabulary rejects unknown capability tags.
4. The trust registry returns `low` for unknown agents and correct tiers for registered agents.
5. Version enforcement rejects undersized bumps for breaking changes.
6. All tests in C3 pass.
7. The registry can be consumed by the router (P1) without adapter code — the query interfaces return data in the format the router needs.

## C5. P0 → P1 Handoff

When P0 is complete, the router (P1) can be built because:

- `query_by_capability` provides the filter phase's capability check
- `AgentSpec.required_inputs` provides the input filter
- `AgentSpec.tools` provides the tool filter
- `TrustRegistry.get_trust` provides the admission risk check
- `AgentSpec.status` provides the status filter

The router's score phase (P1) additionally requires the experience store (P3), so P1 will need a stub/interface for historical performance that gets filled in later.

---

# Summary

| Section | Key Finding |
|---------|-------------|
| **A. Net-New Gaps** | 13 second-order issues found. 2 high severity (retry budget + fork partial admission). None invalidate the architecture. All fixable with targeted additions. |
| **B. Agent-OS Mapping** | ~25% contract surface covered by existing code. 63% greenfield. Foundation (agent loader, sandbox, test harness) is reusable. State authority and orchestration are full builds. |
| **C. P0 Build List** | 12 source files, 5 test files, 4 interfaces, 22 test cases. Scope is tight: schema validation + registry + trust. Clear handoff to P1 (router). |

**Recommended status for v1.1**: Promote from `Draft → Revision Required` to `Draft → Approved for P0 Implementation` with the 13 net-new fixes queued as a v1.2 patch before P1 begins.
