"""Test Chain orchestration — sequential multi-step execution.

Tests: successful chains, failure stops chain, template resolution,
state event emission, context passing.
"""

import pytest
from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, TrustTier
from aegis.harness import Pipeline, DispatcherConfig
from aegis.orchestration import ChainStep, ChainResult, run_chain


# --- Mock client (same pattern as pipeline tests) ---

class MockUsage:
    def __init__(self):
        self.input_tokens = 50
        self.output_tokens = 100

class MockTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text

class MockResponse:
    def __init__(self, text="mock output"):
        self.content = [MockTextBlock(text)]
        self.usage = MockUsage()

class MockClient:
    def __init__(self, responses=None, fail_on=None):
        self.messages = self
        self._responses = responses or []
        self._fail_on = fail_on or set()
        self._call_count = 0
        self.calls = []

    def create(self, **kwargs):
        self._call_count += 1
        self.calls.append(kwargs)
        if self._call_count in self._fail_on:
            raise ConnectionError(f"Simulated failure on call {self._call_count}")
        if self._responses:
            idx = min(self._call_count - 1, len(self._responses) - 1)
            return MockResponse(self._responses[idx])
        return MockResponse(f"output from call {self._call_count}")


def _make_pipeline(client=None) -> Pipeline:
    p = Pipeline(api_client=client or MockClient())
    p.register_agent(AgentSpec(
        agent_id="eng.reviewer", version="1.0.0", status=AgentStatus.ACTIVE,
        role="Code Reviewer", capabilities=["review_code", "debug_issue"],
        required_inputs=["code"], outputs=["review_report"],
        tools=[], constraints=["be_concise"],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    p.register_agent(AgentSpec(
        agent_id="eng.test-writer", version="1.0.0", status=AgentStatus.ACTIVE,
        role="Test Writer", capabilities=["write_tests"],
        required_inputs=["code"], outputs=["test_code"],
        tools=[], constraints=["use_pytest"],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    p.register_agent(AgentSpec(
        agent_id="eng.documenter", version="1.0.0", status=AgentStatus.ACTIVE,
        role="Documenter", capabilities=["generate_report"],
        required_inputs=["task_spec"], outputs=["report"],
        tools=[], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    p.set_trust("eng.reviewer", TrustTier.HIGH, "test")
    p.set_trust("eng.test-writer", TrustTier.HIGH, "test")
    p.set_trust("eng.documenter", TrustTier.MEDIUM, "test")
    return p


class TestSuccessfulChain:

    def test_two_step_chain(self):
        client = MockClient(responses=["Found a bug: division by zero", "def test_div(): ..."])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("review", ["review_code"], ["code"],
                      "Review this code:\ndef div(a,b): return a/b"),
            ChainStep("test", ["write_tests"], ["code"],
                      "Write tests for the code based on this review:\n{{prev.output}}"),
        ]
        result = run_chain(pipeline, "chain-1", steps)

        assert result.success is True
        assert result.steps_completed == 2
        assert result.steps_total == 2
        assert len(result.step_results) == 2
        assert result.step_results[0].agent_id == "eng.reviewer"
        assert result.step_results[1].agent_id == "eng.test-writer"
        assert result.final_output == "def test_div(): ..."
        assert result.total_tokens > 0

    def test_three_step_chain(self):
        client = MockClient(responses=["bug found", "tests written", "docs generated"])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("review", ["review_code"], ["code"], "Review code"),
            ChainStep("test", ["write_tests"], ["code"], "Write tests from: {{prev.output}}"),
            ChainStep("doc", ["generate_report"], ["task_spec"], "Document: {{steps.review.output}}"),
        ]
        result = run_chain(pipeline, "chain-2", steps)

        assert result.success is True
        assert result.steps_completed == 3
        assert result.final_output == "docs generated"

    def test_single_step_chain(self):
        pipeline = _make_pipeline(MockClient(responses=["done"]))
        steps = [ChainStep("only", ["review_code"], ["code"], "Review this")]
        result = run_chain(pipeline, "chain-3", steps)

        assert result.success is True
        assert result.steps_completed == 1


class TestChainFailure:

    def test_failure_stops_chain(self):
        pipeline = _make_pipeline(MockClient())
        steps = [
            ChainStep("good", ["review_code"], ["code"], "Review"),
            ChainStep("bad", ["deploy_service"], ["code"], "Deploy"),  # no agent has this
            ChainStep("never", ["write_tests"], ["code"], "Test"),
        ]
        result = run_chain(pipeline, "chain-4", steps)

        assert result.success is False
        assert result.steps_completed == 1  # only first step ran
        assert result.failed_step == "bad"
        assert len(result.step_results) == 2  # good + bad
        assert result.step_results[0].success is True
        assert result.step_results[1].success is False

    def test_first_step_failure(self):
        pipeline = _make_pipeline(MockClient())
        steps = [
            ChainStep("bad", ["deploy_service"], ["code"], "Deploy"),
            ChainStep("never", ["review_code"], ["code"], "Review"),
        ]
        result = run_chain(pipeline, "chain-5", steps)

        assert result.success is False
        assert result.steps_completed == 0
        assert result.failed_step == "bad"

    def test_empty_chain(self):
        pipeline = _make_pipeline()
        result = run_chain(pipeline, "chain-6", [])
        assert result.success is False
        assert "Empty chain" in result.error


class TestTemplateResolution:

    def test_prev_output_resolved(self):
        client = MockClient(responses=["REVIEW_RESULT", "TESTS_BASED_ON_REVIEW"])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("review", ["review_code"], ["code"], "Review code"),
            ChainStep("test", ["write_tests"], ["code"],
                      "Write tests based on:\n{{prev.output}}"),
        ]
        run_chain(pipeline, "chain-7", steps)

        # Second API call should contain the first step's output
        second_call = client.calls[1]
        user_msg = second_call["messages"][0]["content"]
        assert "REVIEW_RESULT" in user_msg

    def test_named_step_output_resolved(self):
        client = MockClient(responses=["STEP_A_OUT", "STEP_B_OUT", "FINAL"])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("a", ["review_code"], ["code"], "Step A"),
            ChainStep("b", ["write_tests"], ["code"], "Step B"),
            ChainStep("c", ["generate_report"], ["task_spec"],
                      "Combine: {{steps.a.output}} and {{steps.b.output}}"),
        ]
        run_chain(pipeline, "chain-8", steps)

        third_call = client.calls[2]
        user_msg = third_call["messages"][0]["content"]
        assert "STEP_A_OUT" in user_msg
        assert "STEP_B_OUT" in user_msg

    def test_context_resolved(self):
        client = MockClient(responses=["done"])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("review", ["review_code"], ["code"],
                      "Review {{context.language}} code:\n{{context.code}}"),
        ]
        result = run_chain(pipeline, "chain-9", steps,
                          context={"language": "Python", "code": "def add(a,b): return a+b"})

        user_msg = client.calls[0]["messages"][0]["content"]
        assert "Python" in user_msg
        assert "def add" in user_msg


class TestStateEmission:

    def test_chain_emits_events_for_each_step(self):
        pipeline = _make_pipeline(MockClient(responses=["review done", "tests done"]))

        steps = [
            ChainStep("review", ["review_code"], ["code"], "Review"),
            ChainStep("test", ["write_tests"], ["code"], "Test: {{prev.output}}"),
        ]
        run_chain(pipeline, "chain-10", steps)

        # Each step emits 5 events (created, routed, started, output, completed)
        assert pipeline.state.event_count == 10

        # Both tasks should be in completed state
        t1 = pipeline.state.get_task("chain-10.review")
        t2 = pipeline.state.get_task("chain-10.test")
        assert t1.status == "completed"
        assert t2.status == "completed"
        assert t1.agent_id == "eng.reviewer"
        assert t2.agent_id == "eng.test-writer"

    def test_failed_chain_emits_failure_event(self):
        pipeline = _make_pipeline(MockClient())

        steps = [
            ChainStep("good", ["review_code"], ["code"], "Review"),
            ChainStep("bad", ["deploy_service"], ["code"], "Deploy"),
        ]
        run_chain(pipeline, "chain-11", steps)

        good = pipeline.state.get_task("chain-11.good")
        bad = pipeline.state.get_task("chain-11.bad")
        assert good.status == "completed"
        assert bad.status == "failed"

    def test_agent_history_accumulates_across_chain(self):
        pipeline = _make_pipeline(MockClient(responses=["r1", "t1"]))

        steps = [
            ChainStep("review", ["review_code"], ["code"], "Review"),
            ChainStep("test", ["write_tests"], ["code"], "Test"),
        ]
        run_chain(pipeline, "chain-12", steps)

        reviewer_history = pipeline.state.get_agent_history("eng.reviewer")
        writer_history = pipeline.state.get_agent_history("eng.test-writer")
        assert reviewer_history.total_tasks == 1
        assert writer_history.total_tasks == 1


class TestChainResult:

    def test_all_outputs_accessible(self):
        client = MockClient(responses=["review text", "test code", "doc text"])
        pipeline = _make_pipeline(client)

        steps = [
            ChainStep("review", ["review_code"], ["code"], "Review"),
            ChainStep("test", ["write_tests"], ["code"], "Test"),
            ChainStep("doc", ["generate_report"], ["task_spec"], "Doc"),
        ]
        result = run_chain(pipeline, "chain-13", steps)

        assert result.all_outputs == {
            "review": "review text",
            "test": "test code",
            "doc": "doc text",
        }

    def test_duration_tracked(self):
        pipeline = _make_pipeline(MockClient(responses=["a", "b"]))
        steps = [
            ChainStep("a", ["review_code"], ["code"], "A"),
            ChainStep("b", ["write_tests"], ["code"], "B"),
        ]
        result = run_chain(pipeline, "chain-14", steps)
        assert result.total_duration >= 0
