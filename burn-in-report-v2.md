# Burn-In Report v2

**Tasks**: 8 (7 successful, 1 forced failure)  
**Events**: 39  
**Replay**: 8/8 verified  
**Changes since v1**: cost_time_ratio disabled, exploration bonus added  
**Date**: 2026-03-24

---

## Score Improvement: Noise Removed

Before (v1): Every agent scored -20.0 base from cost_time_ratio noise.  
After (v2): Scores are now purely signal-driven.

| Task | v1 Scores (with noise) | v2 Scores (clean) |
|------|----------------------|-------------------|
| First task (preferred=debug_issue) | code-reviewer=20.0, others=-20.0 | code-reviewer=50.0, others=10.0 |
| After 3 runs | code-reviewer=60.0, others=-20.0 | code-reviewer=85.0, others=10.0 |

The +30 shift across the board comes from removing the uniform -20 penalty (+20) and adding the +10 exploration bonus for agents with no history.

---

## Finding 1: Exploration Bonus Is Working But Insufficient

**Evidence**: In phase 2 (no preferred capabilities), underused agents scored 10.0 (exploration bonus) while code-reviewer scored ~40.0 (historical success rate).

```
code-reviewer: historical_success_rate=+40 → 40.0
test-writer:   exploration_no_history=+10   → 10.0
explainer:     exploration_no_history=+10   → 10.0
```

The +10 exploration bonus prevents zero-scoring but doesn't overcome the +40 historical advantage. Code-reviewer won every task in all 8 runs.

**Assessment**: This is working as designed — proven agents SHOULD win. But it means truly untested agents will only get selected when:
- The proven agent fails (failure_recency = -50 would flip the ranking)
- The task prefers a capability only the underused agent has
- The proven agent is denied by governance (risk/trust mismatch)

**Policy decision for later**: If more aggressive exploration is wanted, increase the bonus to ~20-25 or add a "try underused agent every Nth task" policy. Not needed yet.

---

## Finding 2: Forced Dispatch Failure Path Is Clean

**Evidence**: v2-fail-1 used a broken API client. Result:

- Pipeline returned `success=False`, `stage_failed="dispatch"`
- Task state recorded as `"failed"` in State Authority
- System recovered immediately — v2-recover succeeded on the next task
- Replay verified

**One minor issue**: Agent history attribution during multi-candidate failure is imprecise. The dispatcher tried all 3 candidates (code-reviewer → explainer → test-writer), all failed with the same auth error. The pipeline recorded one `task.failed` event. The agent_history projection attributed 1 failure to the explainer (the fallback that happened to be in the in-flight tracker when the final failure event was recorded).

This means code-reviewer was "tried and failed" but its history shows 0 failures. The explainer was also "tried and failed" and got credited with the failure it didn't uniquely own.

**Impact**: Low at current scale. In a system with real dispatch failures, this could distort agent success rates. Fix would be to emit per-candidate failure events in the dispatcher, not just one task-level failure.

**Action**: Log as a known issue. Fix when multi-candidate failure tracking becomes important.

---

## Finding 3: History Accumulation Creates Stable Winner

**Score progression for code-reviewer**:

| Task | Score | Breakdown |
|------|-------|-----------|
| v2-1 | 50.0 | preferred=+25, specialization=+15, exploration=+10 |
| v2-2 | 85.0 | preferred=+25, specialization=+15, history=+40, latency_penalty≈-0, exploration_low=+5 |
| v2-3 | 85.0 | same as v2-2 (3 tasks still below threshold? or stabilized) |
| v2-4+ | ~40.0 | no preferred, history=+40 only |

After 3 successful runs, historical performance dominates all other signals. This is the intended behavior but worth monitoring — in a diverse agent pool, the early winner can become permanently entrenched.

---

## Finding 4: Recovery After Failure Is Immediate

**Evidence**: v2-recover (the task after the forced failure) succeeded on the first attempt. No state corruption, no stale failure data affecting routing, no residual broken client state.

This confirms the pipeline's failure isolation is correct at the integration level, not just in unit tests.

---

## Finding 5: Replay Remains Exact

8/8 tasks replay-verified after the full sequence including a failure and recovery. The event log integrity holds through failure paths.

---

## Known Issues

1. **Multi-candidate failure attribution**: When all candidates fail dispatch, only one agent gets the failure recorded. Should emit per-candidate events.
2. **Exploration bonus too weak for forced diversity**: +10 can't overcome +40 history. By design, but limits organic exploration.
3. **Latency penalty is rounding to -0**: Very small latency differences produce negligible negative scores. May want a minimum threshold.

---

## What This Burn-In Confirmed

| Claim | Status |
|-------|--------|
| cost_time_ratio removal improved score clarity | **Confirmed** — no more uniform noise |
| Exploration bonus prevents zero-scoring | **Confirmed** — underused agents score 10.0, not 0.0 |
| Forced failure records correctly in state | **Confirmed** — task failed, state clean, replay matches |
| Recovery after failure works | **Confirmed** — immediate successful dispatch after failure |
| Rich-get-richer is real but manageable | **Confirmed** — proven agents dominate, by design |
| Replay is exact through failure paths | **Confirmed** — 8/8 |

---

## What Still Does NOT Need Building

- Snapshots (39 events, instant replay)
- Conflict classes beyond replaceable/append_only
- Workflow events
- Budget tracking
- Governance event streams
- Orchestration primitives

The system is stable. The next engineering target is not more infrastructure — it's deciding what real work to route through it.
