"""Aegis Integration Harness — minimal end-to-end execution layer."""

from aegis.harness.dispatcher import Dispatcher, DispatcherConfig, ExecutionResult
from aegis.harness.pipeline import Pipeline, PipelineResult

__all__ = [
    "Dispatcher",
    "DispatcherConfig",
    "ExecutionResult",
    "Pipeline",
    "PipelineResult",
]
