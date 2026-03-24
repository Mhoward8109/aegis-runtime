# Burn-In Report v0

**Tasks**: 10 (8 successful, 2 expected failures)  
**Events**: 44  
**Replay**: 10/10 verified  
**Date**: 2026-03-24

---

## Results Summary

| Task | Agent | Tokens | Duration | Score | Status |
|------|-------|--------|----------|-------|--------|
| burn-1 | code-reviewer | 460 | 11.4s | 20.0 | OK |
| burn-2 | code-reviewer | 321 | 7.1s | 20.0 | OK |
| burn-3 | test-writer | 1,147 | 15.9s | 20.0 | OK |
| burn-4 | schema-designer | 1,130 | 12.9s | -20.0 | OK |
| burn-5 | report-writer | 1,117 | 19.2s | -20.0 | OK |
| burn-6 | — | 0 | 0.0s | — | FAIL (routing) |
| burn-7 | — | 0 | 0.0s | — | FAIL (routing) |
| burn-8 | code-reviewer | 458 | 6.0s | **60.0** | OK |
| burn-9 | code-reviewer | 312 | 4.9s | **60.0** | OK |
| burn-10 | test-writer | 1,150 | 13.4s | -20.0 | OK |

---

## Finding 1: History-fed scoring is working

**Evidence**: burn-8 and burn-9 scored **60.0** for code-reviewer, up from 20.0 in burn-1.

Breakdown for burn-8:
- +25.0 preferred capability (debug_issue)
- +15.0 specialization (overlap ratio 1.00)
- -20.0 cost_time_ratio (default penalty)
- **+40.0 historical success rate** (1.0 × 40 weight)

The experience store accumulated data from burns 1-2 and the router consumed it for burn-8. This is the feedback loop working as designed.

**Impact on tie-breaking**: In burn-2, code-reviewer and explainer were tied at -20.0 (no history yet). By burn-8, code-reviewer had a 40-point advantage from history. The tie-breaking problem identified in the traces is self-correcting as usage accumulates.

---

## Finding 2: Tie-breaking is still arbitrary for first encounters

**Evidence**: burn-2 had three agents tied at -20.0 for `review_code`. Code-reviewer won by iteration order, not by signal.

This will always be true for the very first task of a given type — there's no history to differentiate. After one task completes, history starts discriminating.

**Verdict**: Acceptable cold-start behavior. Not worth engineering a fix. The system self-heals.

---

## Finding 3: The -20.0 cost_time_ratio penalty is universal noise

**Evidence**: Every single agent scored -20.0 on cost_time_ratio. No agent was differentiated by this signal.

Root cause: all agents use default `max_execution_seconds=300` against default task budget of `120s`. The ratio is always 250%, always above the 80% threshold.

**Recommendation**: Disable cost_time_ratio scoring until real cost data exists. It currently adds -20 to every score without discriminating.

---

## Finding 4: burn-3 shows history already influencing multi-agent routing

**Evidence**: Three agents matched `review_code`. Task preferred `write_tests`. Without history (fresh dry run): test-writer=20.0, code-reviewer=-20.0, explainer=-20.0.

But in the actual burn-in, scores were test-writer=20.0 and code-reviewer=20.0 (tied). Why? Because by burn-3, code-reviewer had already completed burns 1-2 with 100% success rate, earning +40 historical performance boost: -20 (cost) + 40 (history) = 20.0.

**This is the feedback loop working in real time.** History accumulated from burns 1-2 was consumed by the router in burn-3, lifting code-reviewer from -20 to +20 and creating a tie with test-writer. The test-writer won the tie because it appeared first in ranking.

**Implication**: After enough runs, the "best" agent for a task type will naturally float to the top. The system is self-tuning.

---

## Finding 5: Event counts are predictable

| Task Type | Events |
|-----------|--------|
| Successful dispatch | 5 (created, routed, started, output, completed) |
| Routing failure | 2 (created, failed) |

44 total events = (8 × 5) + (2 × 2) = 44. Exactly right.

No ghost events. No missing events. No duplicate events. The event model is stable.

---

## Finding 6: Replay is exact

All 10 tasks replayed to identical state. The projection is deterministic from the event log. This confirms:
- Append-only log is correct
- Projection apply() is idempotent per event type
- No state leakage between tasks

---

## Finding 7: Agent history accumulates cleanly

| Agent | Tasks | Success Rate | Avg Latency |
|-------|-------|-------------|-------------|
| code-reviewer | 4 | 100% | 7.3s |
| test-writer | 2 | 100% | 15.9s |
| schema-designer | 1 | 100% | — (wrong task type) |
| report-writer | 1 | 100% | — (wrong task type) |

History is correctly scoped by task type. Schema-designer returns `None` for `review_code` success rate because it only ran `design_schema` tasks. This is correct — no cross-type pollution.

---

## Finding 8: Failure paths are clean

burn-6 (missing capability) and burn-7 (missing input) both:
- Emitted exactly 2 events (created + failed)
- Returned structured failure with correct `stage_failed`
- Did not pollute agent history (no agent was involved)
- Consumed 0 tokens, 0 time

---

## Observations for Next Phase

### What the burn-in says is working:
- Event emission at every lifecycle stage
- Replay correctness
- History-fed scoring (the key win)
- Failure isolation
- Task-local scoping
- No adapter needed between state and router

### What the burn-in says needs attention:
1. **cost_time_ratio is noise** — disable or fix default matching
2. **burn-3 score needs investigation** — possible scoring bug with 3-candidate tie
3. **explainer never gets picked** — always loses to code-reviewer or test-writer. May need different preferred capability patterns to surface it.
4. **No dispatch failures observed** — the API was 100% reliable during burn-in. Fallback behavior is tested in unit tests but not exercised live.

### What the burn-in says is NOT yet needed:
- Snapshots (44 events replays in <1ms)
- Conflict handling (no parallel writes)
- Workflow events (single-task only)
- Budget tracking (no budget pressure observed)
- Governance events (admission was trivial for all tasks)
