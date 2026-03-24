"""Test pipeline integration — full flow with mock API client.

Proves: register → route → dispatch → result pipeline works
without real API calls. Uses a mock client that returns canned responses.
"""

import pytest
from dataclasses import dataclass
from typing import Any

from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, TrustTier
from aegis.models.enums import RiskTier
from aegis.harness import Pipeline, PipelineResult, DispatcherConfig
from aegis.router.types import RouteResult, RoutingFailure


# ---------------------------------------------------------------------------
# Mock Anthropic client
# ---------------------------------------------------------------------------


class MockUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 200):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class MockTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class MockResponse:
    def __init__(self, text: str = "Mock agent output"):
        self.content = [MockTextBlock(text)]
        self.usage = MockUsage()


class MockClient:
    """Mock Anthropic client that records calls and returns canned responses."""

    def __init__(self, response_text: str = "Mock agent output", fail: bool = False):
        self.messages = self
        self._response_text = response_text
        self._fail = fail
        self.calls: list[dict] = []

    def create(self, **kwargs) -> MockResponse:
        self.calls.append(kwargs)
        if self._fail:
            raise ConnectionError("Mock API failure")
        return MockResponse(self._response_text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pipeline(client=None) -> Pipeline:
    p = Pipeline(api_client=client or MockClient())
    p.register_agent(AgentSpec(
        agent_id="eng.frontend",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Frontend Dev",
        capabilities=["build_ui", "integrate_api"],
        required_inputs=["task_spec"],
        outputs=["ui_code"], tools=["editor"], constraints=["no_inline_styles"],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))
    p.register_agent(AgentSpec(
        agent_id="eng.backend",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Backend Dev",
        capabilities=["write_backend", "integrate_api"],
        required_inputs=["task_spec", "api_schema"],
        outputs=["backend_code"], tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))
    p.set_trust("eng.frontend", TrustTier.MEDIUM, "test")
    p.set_trust("eng.backend", TrustTier.HIGH, "test")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessfulPipeline:

    def test_full_pipeline_returns_output(self):
        client = MockClient("Login form component code here")
        pipeline = _make_pipeline(client)

        result = pipeline.run(
            task_id="t1",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build a login form component",
        )

        assert result.success is True
        assert result.output == "Login form component code here"
        assert result.agent_id == "eng.frontend"
        assert result.stage_failed == ""

    def test_tokens_and_duration_populated(self):
        pipeline = _make_pipeline()
        result = pipeline.run(
            task_id="t2",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build something",
        )
        assert result.tokens_used == 300  # 100 + 200 from mock
        assert result.duration_seconds >= 0

    def test_routing_scores_in_result(self):
        pipeline = _make_pipeline()
        result = pipeline.run(
            task_id="t3",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build something",
        )
        assert result.routing_scores is not None
        assert "eng.frontend" in result.routing_scores

    def test_api_called_with_system_prompt(self):
        client = MockClient()
        pipeline = _make_pipeline(client)
        pipeline.run(
            task_id="t4",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build a form",
        )

        assert len(client.calls) == 1
        call = client.calls[0]
        assert "Frontend Dev" in call["system"]
        assert "no_inline_styles" in call["system"]
        assert call["messages"][0]["content"] == "Build a form"

    def test_task_context_included_in_prompt(self):
        client = MockClient()
        pipeline = _make_pipeline(client)
        pipeline.run(
            task_id="t5",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build a form",
            task_context={"framework": "React", "style": "Tailwind"},
        )

        user_msg = client.calls[0]["messages"][0]["content"]
        assert "React" in user_msg
        assert "Tailwind" in user_msg


class TestRoutingFailures:

    def test_no_matching_capability(self):
        pipeline = _make_pipeline()
        result = pipeline.run(
            task_id="t6",
            required_capabilities=["deploy_service"],
            inputs_available=["task_spec"],
            prompt="Deploy the app",
        )

        assert result.success is False
        assert result.stage_failed == "routing"
        assert "no_suitable_agent" in result.error

    def test_missing_required_inputs(self):
        pipeline = _make_pipeline()
        result = pipeline.run(
            task_id="t7",
            required_capabilities=["write_backend"],
            inputs_available=["task_spec"],  # missing api_schema
            prompt="Write the API",
        )

        assert result.success is False
        assert result.stage_failed == "routing"

    def test_trust_blocks_medium_risk(self):
        client = MockClient()
        pipeline = Pipeline(api_client=client)
        pipeline.register_agent(AgentSpec(
            agent_id="eng.untrusted",
            version="1.0.0", status=AgentStatus.ACTIVE, role="Dev",
            capabilities=["build_ui"],
            required_inputs=["task_spec"],
            outputs=["code"], tools=[], constraints=[],
            evaluation=EvaluationConfig(success_criteria=["pass"]),
        ))
        # No trust set → defaults to LOW

        result = pipeline.run(
            task_id="t8",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build",
            risk_tier=RiskTier.MEDIUM,
        )

        assert result.success is False
        assert result.stage_failed == "routing"


class TestDispatchFailures:

    def test_api_failure_returns_error(self):
        client = MockClient(fail=True)
        pipeline = _make_pipeline(client)

        result = pipeline.run(
            task_id="t9",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build a form",
        )

        assert result.success is False
        assert result.stage_failed == "dispatch"
        assert "ConnectionError" in result.error

    def test_fallback_on_failure(self):
        """If primary fails, dispatcher tries fallback candidates."""
        call_count = 0

        class FailOnceClient:
            def __init__(self):
                self.messages = self
                self.call_count = 0

            def create(self, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    raise ConnectionError("First call fails")
                return MockResponse("Fallback succeeded")

        client = FailOnceClient()
        pipeline = Pipeline(api_client=client)

        # Register two agents with same capability
        pipeline.register_agent(AgentSpec(
            agent_id="eng.primary",
            version="1.0.0", status=AgentStatus.ACTIVE, role="Primary",
            capabilities=["build_ui", "integrate_api"],
            required_inputs=["task_spec"],
            outputs=["ui_code"], tools=[], constraints=[],
            evaluation=EvaluationConfig(success_criteria=["pass"]),
        ))
        pipeline.register_agent(AgentSpec(
            agent_id="eng.fallback",
            version="1.0.0", status=AgentStatus.ACTIVE, role="Fallback",
            capabilities=["build_ui"],
            required_inputs=["task_spec"],
            outputs=["ui_code"], tools=[], constraints=[],
            evaluation=EvaluationConfig(success_criteria=["pass"]),
        ))

        result = pipeline.run(
            task_id="t10",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
            prompt="Build a form",
        )

        assert result.success is True
        assert result.output == "Fallback succeeded"
        assert client.call_count == 2


class TestDryRun:

    def test_dry_run_routes_without_dispatch(self):
        pipeline = _make_pipeline()
        outcome = pipeline.dry_run(
            task_id="t11",
            required_capabilities=["build_ui"],
            inputs_available=["task_spec"],
        )

        assert isinstance(outcome, RouteResult)
        assert outcome.primary.agent_id == "eng.frontend"

    def test_dry_run_failure(self):
        pipeline = _make_pipeline()
        outcome = pipeline.dry_run(
            task_id="t12",
            required_capabilities=["deploy_service"],
            inputs_available=["task_spec"],
        )

        assert isinstance(outcome, RoutingFailure)
