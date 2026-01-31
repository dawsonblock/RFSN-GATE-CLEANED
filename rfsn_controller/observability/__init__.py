"""RFSN Observability Package.

Provides metrics, logging, and tracing for the RFSN controller:
- Prometheus metrics for repair attempts, LLM calls, patches, tests
- Structured logging with structlog
- Decorators for automatic tracking
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable, TypeVar

# Check for optional dependencies
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


# Configure structured logging if available
if HAS_STRUCTLOG:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()
else:
    # Fallback to standard logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("rfsn")


# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

if HAS_PROMETHEUS:
    # Repair metrics
    repair_attempts_total = Counter(
        "rfsn_repair_attempts_total",
        "Total number of repair attempts",
        ["status"],  # success, failed, timeout
    )
    
    repair_duration_seconds = Histogram(
        "rfsn_repair_duration_seconds",
        "Duration of repair operations",
        buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800],
    )
    
    # LLM metrics
    llm_calls_total = Counter(
        "rfsn_llm_calls_total",
        "Total LLM API calls",
        ["model", "status"],
    )
    
    llm_tokens_used = Counter(
        "rfsn_llm_tokens_used_total",
        "Total tokens consumed",
        ["model", "type"],  # type: prompt, completion
    )
    
    llm_call_duration_seconds = Histogram(
        "rfsn_llm_call_duration_seconds",
        "LLM call duration",
        ["model"],
    )
    
    llm_cost_usd = Counter(
        "rfsn_llm_cost_usd_total",
        "Total LLM cost in USD",
        ["model"],
    )
    
    # Beam search metrics
    beam_search_candidates = Gauge(
        "rfsn_beam_search_candidates",
        "Current number of beam search candidates",
    )
    
    beam_search_iterations = Counter(
        "rfsn_beam_search_iterations_total",
        "Total beam search iterations",
    )
    
    # Gate metrics
    gate_validations_total = Counter(
        "rfsn_gate_validations_total",
        "Gate validation attempts",
        ["result"],  # approved, rejected
    )
    
    # Patch metrics
    patches_applied_total = Counter(
        "rfsn_patches_applied_total",
        "Total patches applied",
        ["outcome"],  # success, failed, reverted
    )
    
    # Test metrics
    test_executions_total = Counter(
        "rfsn_test_executions_total",
        "Test execution attempts",
        ["result"],  # passed, failed, timeout
    )
    
    # Strategy metrics
    strategy_selections_total = Counter(
        "rfsn_strategy_selections_total",
        "Total strategy selections",
        ["strategy"],
    )
    
    strategy_outcomes_total = Counter(
        "rfsn_strategy_outcomes_total",
        "Strategy outcomes",
        ["strategy", "outcome"],  # success, failure, regression
    )
else:
    # Dummy metrics when Prometheus not available
    class DummyMetric:
        def labels(self, **kwargs):
            return self
        def inc(self, amount=1):
            pass
        def dec(self, amount=1):
            pass
        def set(self, value):
            pass
        def observe(self, value):
            pass
    
    repair_attempts_total = DummyMetric()
    repair_duration_seconds = DummyMetric()
    llm_calls_total = DummyMetric()
    llm_tokens_used = DummyMetric()
    llm_call_duration_seconds = DummyMetric()
    llm_cost_usd = DummyMetric()
    beam_search_candidates = DummyMetric()
    beam_search_iterations = DummyMetric()
    gate_validations_total = DummyMetric()
    patches_applied_total = DummyMetric()
    test_executions_total = DummyMetric()
    strategy_selections_total = DummyMetric()
    strategy_outcomes_total = DummyMetric()


# =============================================================================
# METRICS SERVER
# =============================================================================

def start_metrics_server(port: int = 9090) -> None:
    """Start Prometheus metrics HTTP server.
    
    Args:
        port: Port to expose metrics on (default: 9090)
    """
    if HAS_PROMETHEUS:
        start_http_server(port)
        logger.info("metrics_server_started", port=port)
    else:
        logger.warning("prometheus_client not installed, metrics disabled")


# =============================================================================
# CONTEXT MANAGERS FOR TRACKING
# =============================================================================

@contextmanager
def track_repair_attempt():
    """Context manager to track repair attempt metrics.
    
    Usage:
        with track_repair_attempt():
            result = run_repair(config)
    """
    start_time = time.time()
    status = "failed"
    
    try:
        yield
        status = "success"
    except TimeoutError:
        status = "timeout"
        raise
    except Exception:
        status = "failed"
        raise
    finally:
        duration = time.time() - start_time
        repair_duration_seconds.observe(duration)
        repair_attempts_total.labels(status=status).inc()
        logger.info(
            "repair_attempt_completed",
            status=status,
            duration_seconds=round(duration, 2),
        )


@contextmanager
def track_llm_call(model: str):
    """Context manager to track LLM API calls.
    
    Usage:
        with track_llm_call("deepseek-v3"):
            response = await client.call(...)
    """
    start_time = time.time()
    status = "success"
    
    try:
        yield
        llm_calls_total.labels(model=model, status="success").inc()
    except Exception as e:
        status = "failed"
        llm_calls_total.labels(model=model, status="failed").inc()
        logger.error("llm_call_failed", model=model, error=str(e))
        raise
    finally:
        duration = time.time() - start_time
        llm_call_duration_seconds.labels(model=model).observe(duration)


# =============================================================================
# TRACKING FUNCTIONS
# =============================================================================

def track_tokens(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Track token usage.
    
    Args:
        model: Model name
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens
    """
    llm_tokens_used.labels(model=model, type="prompt").inc(prompt_tokens)
    llm_tokens_used.labels(model=model, type="completion").inc(completion_tokens)


def track_cost(model: str, cost_usd: float) -> None:
    """Track LLM cost.
    
    Args:
        model: Model name
        cost_usd: Cost in USD
    """
    llm_cost_usd.labels(model=model).inc(cost_usd)


def track_gate_validation(approved: bool) -> None:
    """Track gate validation result.
    
    Args:
        approved: Whether the gate approved the action
    """
    result = "approved" if approved else "rejected"
    gate_validations_total.labels(result=result).inc()


def track_patch(outcome: str) -> None:
    """Track patch application.
    
    Args:
        outcome: One of "success", "failed", "reverted"
    """
    patches_applied_total.labels(outcome=outcome).inc()


def track_test_execution(result: str) -> None:
    """Track test execution.
    
    Args:
        result: One of "passed", "failed", "timeout"
    """
    test_executions_total.labels(result=result).inc()


def track_strategy_selection(strategy: str) -> None:
    """Track strategy selection by the bandit.
    
    Args:
        strategy: Strategy name
    """
    strategy_selections_total.labels(strategy=strategy).inc()


def track_strategy_outcome(strategy: str, outcome: str) -> None:
    """Track strategy outcome.
    
    Args:
        strategy: Strategy name
        outcome: One of "success", "failure", "regression"
    """
    strategy_outcomes_total.labels(strategy=strategy, outcome=outcome).inc()


def set_beam_candidates(count: int) -> None:
    """Set the current beam search candidate count.
    
    Args:
        count: Number of active candidates
    """
    beam_search_candidates.set(count)


def increment_beam_iteration() -> None:
    """Increment beam search iteration counter."""
    beam_search_iterations.inc()


# =============================================================================
# DECORATORS
# =============================================================================

F = TypeVar("F", bound=Callable)


def observed(metric_name: str = "function_call"):
    """Decorator to automatically track function calls.
    
    Usage:
        @observed("my_function")
        def my_function():
            pass
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                logger.debug(
                    f"{metric_name}_completed",
                    duration_ms=round((time.time() - start_time) * 1000, 2),
                )
                return result
            except Exception as e:
                logger.error(
                    f"{metric_name}_failed",
                    error=str(e),
                    duration_ms=round((time.time() - start_time) * 1000, 2),
                )
                raise
        return wrapper  # type: ignore
    return decorator


def async_observed(metric_name: str = "function_call"):
    """Decorator to automatically track async function calls.
    
    Usage:
        @async_observed("my_async_function")
        async def my_async_function():
            pass
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                logger.debug(
                    f"{metric_name}_completed",
                    duration_ms=round((time.time() - start_time) * 1000, 2),
                )
                return result
            except Exception as e:
                logger.error(
                    f"{metric_name}_failed",
                    error=str(e),
                    duration_ms=round((time.time() - start_time) * 1000, 2),
                )
                raise
        return wrapper  # type: ignore
    return decorator


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Logger
    "logger",
    # Metrics server
    "start_metrics_server",
    # Context managers
    "track_repair_attempt",
    "track_llm_call",
    # Tracking functions
    "track_tokens",
    "track_cost",
    "track_gate_validation",
    "track_patch",
    "track_test_execution",
    "track_strategy_selection",
    "track_strategy_outcome",
    "set_beam_candidates",
    "increment_beam_iteration",
    # Decorators
    "observed",
    "async_observed",
    # Raw metrics (for advanced usage)
    "repair_attempts_total",
    "repair_duration_seconds",
    "llm_calls_total",
    "llm_tokens_used",
    "llm_call_duration_seconds",
    "llm_cost_usd",
    "beam_search_candidates",
    "beam_search_iterations",
    "gate_validations_total",
    "patches_applied_total",
    "test_executions_total",
    "strategy_selections_total",
    "strategy_outcomes_total",
]
