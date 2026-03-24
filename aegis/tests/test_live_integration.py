"""Real integration test — calls Claude API.

Run with: python -m aegis.tests.test_live_integration

Requires ANTHROPIC_API_KEY environment variable.
This is NOT part of the standard test suite (no test_ prefix discovery
by default). Run explicitly when you want to verify live API integration.
"""

import os
import sys


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set. Skipping live integration test.")
        print("Set it and re-run to test real API dispatch.")
        return

    # Import here so missing anthropic package doesn't crash on import
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed. Run: pip install anthropic")
        return

    from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, TrustTier
    from aegis.harness import Pipeline

    print("=" * 60)
    print("AEGIS LIVE INTEGRATION TEST")
    print("=" * 60)

    # --- Setup ---
    pipeline = Pipeline()

    pipeline.register_agent(AgentSpec(
        agent_id="engineering.code-reviewer",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Code Reviewer",
        capabilities=["review_code", "debug_issue"],
        required_inputs=["code"],
        outputs=["review_report"],
        tools=["code_editor", "linter"],
        constraints=["be_concise", "focus_on_bugs_not_style"],
        evaluation=EvaluationConfig(
            success_criteria=["review_complete"],
        ),
    ))

    pipeline.register_agent(AgentSpec(
        agent_id="engineering.explainer",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Code Explainer",
        capabilities=["review_code", "analyze_data"],
        required_inputs=["code"],
        outputs=["explanation"],
        tools=[],
        constraints=["explain_at_junior_level"],
        evaluation=EvaluationConfig(
            success_criteria=["explanation_clear"],
        ),
    ))

    pipeline.set_trust("engineering.code-reviewer", TrustTier.MEDIUM, "test")
    pipeline.set_trust("engineering.explainer", TrustTier.MEDIUM, "test")

    # --- Test 1: Dry run (no API call) ---
    print("\n--- Test 1: Dry Run ---")
    from aegis.router.types import RouteResult
    outcome = pipeline.dry_run(
        task_id="dry-1",
        required_capabilities=["review_code"],
        inputs_available=["code"],
        preferred_capabilities=["debug_issue"],
    )

    if isinstance(outcome, RouteResult):
        print(f"Primary: {outcome.primary.agent_id} (score: {outcome.primary.score:.1f})")
        for fb in outcome.fallbacks:
            print(f"Fallback: {fb.agent_id} (score: {fb.score:.1f})")
        print("Dry run: PASS")
    else:
        print(f"Routing failed: {outcome.reason.value}")
        print("Dry run: FAIL")
        return

    # --- Test 2: Live dispatch ---
    print("\n--- Test 2: Live Dispatch ---")

    code_to_review = '''
def calculate_average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)
'''

    result = pipeline.run(
        task_id="live-1",
        required_capabilities=["review_code"],
        inputs_available=["code"],
        preferred_capabilities=["debug_issue"],
        prompt=f"Review this Python function for bugs:\n\n```python\n{code_to_review}\n```",
    )

    if result.success:
        print(f"Agent: {result.agent_id}")
        print(f"Tokens: {result.tokens_used}")
        print(f"Duration: {result.duration_seconds}s")
        print(f"Output preview: {result.output[:200]}...")
        print("Live dispatch: PASS")
    else:
        print(f"Failed at: {result.stage_failed}")
        print(f"Error: {result.error}")
        print("Live dispatch: FAIL")

    # --- Test 3: Routing failure (no matching agents) ---
    print("\n--- Test 3: Routing Failure ---")
    result = pipeline.run(
        task_id="fail-1",
        required_capabilities=["deploy_service"],
        inputs_available=["code"],
        prompt="Deploy this",
    )

    if not result.success and result.stage_failed == "routing":
        print(f"Correctly failed at routing: {result.error}")
        print("Routing failure: PASS")
    else:
        print("Expected routing failure but got something else")
        print("Routing failure: FAIL")

    print("\n" + "=" * 60)
    print("INTEGRATION TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
