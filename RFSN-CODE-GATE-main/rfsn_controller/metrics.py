"""Prometheus metrics for RFSN Controller.

Provides instrumentation for monitoring and observability of the RFSN system.
Exposes metrics for proposals, repairs, tests, cache, LLM calls, and system health.

Example:
    from rfsn_controller.metrics import (
        proposals_total, repair_duration, active_repairs
    )
    
    # Track proposal generation
    proposals_total.labels(intent='repair', action_type='edit_file').inc()
    
    # Track repair duration
    with repair_duration.time():
        result = perform_repair()
    
    # Track active repairs
    active_repairs.inc()
    try:
        perform_repair()
    finally:
        active_repairs.dec()
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

__all__ = [
    # Proposal metrics
    "proposals_total",
    "proposals_rejected",
    "proposals_accepted",
    # Repair metrics
    "repair_duration",
    "repair_iterations",
    "active_repairs",
    "repair_outcomes",
    # Test metrics
    "tests_run",
    "test_duration",
    "test_failures",
    # Cache metrics
    "cache_hits",
    "cache_misses",
    "cache_size_bytes",
    # LLM metrics
    "llm_calls",
    "llm_tokens",
    "llm_latency",
    "llm_errors",
    # Gate metrics
    "gate_validations",
    "gate_rejections",
    # System metrics
    "system_info",
]


# =============================================================================
# Proposal Metrics
# =============================================================================

proposals_total = Counter(
    "rfsn_proposals_total",
    "Total number of proposals generated",
    ["intent", "action_type"],
)

proposals_rejected = Counter(
    "rfsn_proposals_rejected_total",
    "Total number of proposals rejected by gate",
    ["rejection_type", "phase"],
)

proposals_accepted = Counter(
    "rfsn_proposals_accepted_total",
    "Total number of proposals accepted by gate",
    ["intent", "phase"],
)


# =============================================================================
# Repair Metrics
# =============================================================================

repair_duration = Histogram(
    "rfsn_repair_duration_seconds",
    "Time taken to complete a repair session",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
)

repair_iterations = Histogram(
    "rfsn_repair_iterations",
    "Number of iterations per repair session",
    buckets=[1, 3, 5, 10, 20, 50, 100, 200],
)

active_repairs = Gauge(
    "rfsn_active_repairs",
    "Number of active repair sessions",
)

repair_outcomes = Counter(
    "rfsn_repair_outcomes_total",
    "Repair session outcomes",
    ["outcome"],  # success, timeout, max_iterations, error
)


# =============================================================================
# Test Metrics
# =============================================================================

tests_run = Counter(
    "rfsn_tests_run_total",
    "Total number of tests executed",
    ["outcome"],  # pass, fail, skip, error
)

test_duration = Histogram(
    "rfsn_test_duration_seconds",
    "Test execution duration",
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300],
)

test_failures = Counter(
    "rfsn_test_failures_total",
    "Test failures by test path",
    ["test_path"],
)


# =============================================================================
# Cache Metrics
# =============================================================================

cache_hits = Counter(
    "rfsn_cache_hits_total",
    "Cache hits by tier",
    ["tier"],  # memory, disk, semantic
)

cache_misses = Counter(
    "rfsn_cache_misses_total",
    "Cache misses",
)

cache_size_bytes = Gauge(
    "rfsn_cache_size_bytes",
    "Current cache size in bytes",
    ["tier"],
)


# =============================================================================
# LLM Metrics
# =============================================================================

llm_calls = Counter(
    "rfsn_llm_calls_total",
    "Total LLM API calls",
    ["model", "status"],  # success, error, timeout
)

llm_tokens = Counter(
    "rfsn_llm_tokens_total",
    "Total LLM tokens used",
    ["model", "type"],  # input, output
)

llm_latency = Histogram(
    "rfsn_llm_latency_seconds",
    "LLM API response time",
    ["model"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

llm_errors = Counter(
    "rfsn_llm_errors_total",
    "LLM API errors",
    ["model", "error_type"],
)


# =============================================================================
# Gate Metrics
# =============================================================================

gate_validations = Counter(
    "rfsn_gate_validations_total",
    "Total gate validation attempts",
    ["result"],  # accepted, rejected
)

gate_rejections = Counter(
    "rfsn_gate_rejections_total",
    "Gate rejections by type",
    ["rejection_type"],  # schema, ordering, bounds, invariant
)


# =============================================================================
# System Metrics
# =============================================================================

system_info = Info("rfsn_system", "RFSN system information")


# =============================================================================
# Convenience Functions
# =============================================================================

def initialize_system_info(
    version: str = "0.3.0",
    planner: str = "v5",
    python_version: str = "3.12",
) -> None:
    """Initialize system information metrics.
    
    Args:
        version: RFSN version
        planner: Planner version in use
        python_version: Python version
        
    Example:
        from rfsn_controller.metrics import initialize_system_info
        
        initialize_system_info(version="0.3.0", planner="v5")
    """
    system_info.info({
        "version": version,
        "planner": planner,
        "python_version": python_version,
    })


def record_proposal(intent: str, action_type: str) -> None:
    """Record a proposal being generated.
    
    Args:
        intent: Proposal intent (repair, refactor, feature, test, analyze)
        action_type: Action type (edit_file, add_file, delete_file, run_tests, run_command)
    """
    proposals_total.labels(intent=intent, action_type=action_type).inc()


def record_gate_result(accepted: bool, rejection_type: str | None = None, phase: str = "unknown") -> None:
    """Record a gate validation result.
    
    Args:
        accepted: Whether proposal was accepted
        rejection_type: Type of rejection if rejected (schema, ordering, bounds, invariant)
        phase: Current planner phase
    """
    if accepted:
        gate_validations.labels(result="accepted").inc()
    else:
        gate_validations.labels(result="rejected").inc()
        if rejection_type:
            gate_rejections.labels(rejection_type=rejection_type).inc()


def record_test_result(outcome: str, test_path: str | None = None, duration: float | None = None) -> None:
    """Record a test execution result.
    
    Args:
        outcome: Test outcome (pass, fail, skip, error)
        test_path: Path to the test (optional)
        duration: Test duration in seconds (optional)
    """
    tests_run.labels(outcome=outcome).inc()
    
    if test_path and outcome == "fail":
        test_failures.labels(test_path=test_path).inc()
    
    if duration is not None:
        test_duration.observe(duration)


def record_cache_access(hit: bool, tier: str = "memory") -> None:
    """Record a cache access.
    
    Args:
        hit: Whether cache hit or miss
        tier: Cache tier (memory, disk, semantic)
    """
    if hit:
        cache_hits.labels(tier=tier).inc()
    else:
        cache_misses.inc()


def record_llm_call(
    model: str,
    success: bool,
    latency: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_type: str | None = None,
) -> None:
    """Record an LLM API call.
    
    Args:
        model: LLM model name
        success: Whether call succeeded
        latency: Response time in seconds (optional)
        input_tokens: Number of input tokens (optional)
        output_tokens: Number of output tokens (optional)
        error_type: Error type if failed (optional)
    """
    status = "success" if success else "error"
    llm_calls.labels(model=model, status=status).inc()
    
    if latency is not None:
        llm_latency.labels(model=model).observe(latency)
    
    if input_tokens is not None:
        llm_tokens.labels(model=model, type="input").inc(input_tokens)
    
    if output_tokens is not None:
        llm_tokens.labels(model=model, type="output").inc(output_tokens)
    
    if not success and error_type:
        llm_errors.labels(model=model, error_type=error_type).inc()
