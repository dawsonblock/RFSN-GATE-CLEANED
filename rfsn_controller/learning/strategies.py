"""Centralized fix strategy definitions with metadata.

This module defines all available fix strategies for the StrategyBandit,
including metadata about when each strategy is applicable and how it maps
to proposal templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorCategory(Enum):
    """Categories of errors that strategies can address."""
    
    TYPE_ERROR = "type_error"
    VALUE_ERROR = "value_error"
    INDEX_ERROR = "index_error"
    KEY_ERROR = "key_error"
    ATTRIBUTE_ERROR = "attribute_error"
    IMPORT_ERROR = "import_error"
    SYNTAX_ERROR = "syntax_error"
    RUNTIME_ERROR = "runtime_error"
    ASSERTION_ERROR = "assertion_error"
    RESOURCE_ERROR = "resource_error"
    ASYNC_ERROR = "async_error"
    LOGIC_ERROR = "logic_error"


@dataclass
class StrategyDefinition:
    """Complete definition of a fix strategy."""
    
    name: str
    description: str
    applicable_errors: list[ErrorCategory] = field(default_factory=list)
    priority: float = 1.0  # Higher = more likely to try first
    guard_type: str | None = None  # Maps to proposal guard type
    is_defensive: bool = False  # True if adds guards/checks
    keywords: list[str] = field(default_factory=list)  # Search keywords
    
    def matches_error(self, error_type: str) -> bool:
        """Check if strategy is applicable to an error type."""
        error_lower = error_type.lower()
        for cat in self.applicable_errors:
            if cat.value.replace("_", "") in error_lower:
                return True
        return any(kw.lower() in error_lower for kw in self.keywords)


# =============================================================================
# STRATEGY DEFINITIONS - Organized by Category
# =============================================================================

# --- Null/None Handling ---
GUARD_NONE = StrategyDefinition(
    name="guard_none",
    description="Add null/None check before attribute access",
    applicable_errors=[ErrorCategory.ATTRIBUTE_ERROR, ErrorCategory.TYPE_ERROR],
    priority=1.5,
    guard_type="none_check",
    is_defensive=True,
    keywords=["NoneType", "has no attribute", "'None'"],
)

NONE_COALESCE = StrategyDefinition(
    name="none_coalesce",
    description="Use default value when None encountered",
    applicable_errors=[ErrorCategory.ATTRIBUTE_ERROR, ErrorCategory.TYPE_ERROR],
    priority=1.3,
    guard_type="none_check",
    is_defensive=True,
    keywords=["NoneType", "None"],
)

# --- Boundary/Index Handling ---
BOUNDARY_CHECK = StrategyDefinition(
    name="boundary_check",
    description="Add bounds validation before index access",
    applicable_errors=[ErrorCategory.INDEX_ERROR],
    priority=1.5,
    guard_type="boundary_check",
    is_defensive=True,
    keywords=["IndexError", "out of range", "index"],
)

FIX_OFF_BY_ONE = StrategyDefinition(
    name="fix_off_by_one",
    description="Fix off-by-one error in loop or index",
    applicable_errors=[ErrorCategory.INDEX_ERROR, ErrorCategory.ASSERTION_ERROR],
    priority=1.4,
    keywords=["off by one", "fence post", "boundary"],
)

EMPTY_CASE = StrategyDefinition(
    name="empty_case",
    description="Handle empty collection case explicitly",
    applicable_errors=[ErrorCategory.INDEX_ERROR, ErrorCategory.VALUE_ERROR],
    priority=1.3,
    guard_type="empty_check",
    is_defensive=True,
    keywords=["empty", "no elements", "length 0"],
)

# --- Type Handling ---
TYPE_CHECK = StrategyDefinition(
    name="type_check",
    description="Add type validation before operation",
    applicable_errors=[ErrorCategory.TYPE_ERROR],
    priority=1.4,
    guard_type="type_check",
    is_defensive=True,
    keywords=["TypeError", "unsupported operand", "expected"],
)

FIX_TYPE_COERCION = StrategyDefinition(
    name="fix_type_coercion",
    description="Add explicit type conversion",
    applicable_errors=[ErrorCategory.TYPE_ERROR],
    priority=1.2,
    keywords=["cannot convert", "invalid literal", "type"],
)

FIX_TYPING = StrategyDefinition(
    name="fix_typing",
    description="Fix type annotation or generic usage",
    applicable_errors=[ErrorCategory.TYPE_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.0,
    keywords=["annotation", "generic", "typing"],
)

# --- Dictionary/Key Handling ---
FIX_KEY_ERROR = StrategyDefinition(
    name="fix_key_error",
    description="Handle missing dictionary key",
    applicable_errors=[ErrorCategory.KEY_ERROR],
    priority=1.5,
    guard_type="key_check",
    is_defensive=True,
    keywords=["KeyError", "key", "not found"],
)

USE_GET_DEFAULT = StrategyDefinition(
    name="use_get_default",
    description="Use dict.get() with default instead of []",
    applicable_errors=[ErrorCategory.KEY_ERROR],
    priority=1.4,
    keywords=["KeyError", "dictionary"],
)

# --- Arithmetic Handling ---
FIX_DIVISION_BY_ZERO = StrategyDefinition(
    name="fix_division_by_zero",
    description="Guard against division by zero",
    applicable_errors=[ErrorCategory.RUNTIME_ERROR, ErrorCategory.VALUE_ERROR],
    priority=1.5,
    guard_type="zero_check",
    is_defensive=True,
    keywords=["ZeroDivisionError", "division by zero", "divide"],
)

FIX_OVERFLOW = StrategyDefinition(
    name="fix_overflow",
    description="Handle numeric overflow",
    applicable_errors=[ErrorCategory.RUNTIME_ERROR, ErrorCategory.VALUE_ERROR],
    priority=1.1,
    keywords=["OverflowError", "too large", "overflow"],
)

FIX_PRECISION = StrategyDefinition(
    name="fix_precision",
    description="Fix floating point precision issues",
    applicable_errors=[ErrorCategory.ASSERTION_ERROR, ErrorCategory.VALUE_ERROR],
    priority=1.0,
    keywords=["precision", "float", "decimal", "rounding"],
)

# --- String Handling ---
FIX_ENCODING = StrategyDefinition(
    name="fix_encoding",
    description="Fix string encoding/decoding issues",
    applicable_errors=[ErrorCategory.VALUE_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.2,
    keywords=["UnicodeDecodeError", "UnicodeEncodeError", "codec", "encoding"],
)

FIX_FORMAT_STRING = StrategyDefinition(
    name="fix_format_string",
    description="Fix string formatting issues",
    applicable_errors=[ErrorCategory.VALUE_ERROR, ErrorCategory.TYPE_ERROR],
    priority=1.1,
    keywords=["format", "f-string", "%", "str.format"],
)

FIX_REGEX = StrategyDefinition(
    name="fix_regex",
    description="Fix regular expression pattern",
    applicable_errors=[ErrorCategory.VALUE_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.0,
    keywords=["regex", "re.", "pattern", "match"],
)

# --- Import/Module Handling ---
FIX_IMPORT = StrategyDefinition(
    name="fix_import",
    description="Fix import statement or path",
    applicable_errors=[ErrorCategory.IMPORT_ERROR],
    priority=1.5,
    keywords=["ImportError", "ModuleNotFoundError", "No module named"],
)

FIX_CIRCULAR_IMPORT = StrategyDefinition(
    name="fix_circular_import",
    description="Break circular import dependency",
    applicable_errors=[ErrorCategory.IMPORT_ERROR],
    priority=1.3,
    keywords=["circular", "import", "partially initialized"],
)

# --- Async/Concurrency Handling ---
FIX_AWAIT_MISSING = StrategyDefinition(
    name="fix_await_missing",
    description="Add missing await keyword",
    applicable_errors=[ErrorCategory.ASYNC_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.4,
    keywords=["coroutine", "await", "async", "was never awaited"],
)

FIX_DEADLOCK = StrategyDefinition(
    name="fix_deadlock",
    description="Fix potential deadlock in locking",
    applicable_errors=[ErrorCategory.ASYNC_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.2,
    keywords=["deadlock", "lock", "timeout", "blocked"],
)

FIX_RACE_CONDITION = StrategyDefinition(
    name="fix_race_condition",
    description="Add synchronization to prevent race",
    applicable_errors=[ErrorCategory.ASYNC_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.1,
    keywords=["race", "concurrent", "thread", "atomic"],
)

# --- Resource Handling ---
FIX_FILE_HANDLE = StrategyDefinition(
    name="fix_file_handle",
    description="Ensure file handle is properly closed",
    applicable_errors=[ErrorCategory.RESOURCE_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.3,
    keywords=["file", "handle", "closed", "ResourceWarning"],
)

FIX_CONNECTION_LEAK = StrategyDefinition(
    name="fix_connection_leak",
    description="Fix connection/resource leak",
    applicable_errors=[ErrorCategory.RESOURCE_ERROR],
    priority=1.2,
    keywords=["connection", "leak", "pool", "exhausted"],
)

FIX_MEMORY = StrategyDefinition(
    name="fix_memory",
    description="Fix memory-related issue",
    applicable_errors=[ErrorCategory.RESOURCE_ERROR, ErrorCategory.RUNTIME_ERROR],
    priority=1.0,
    keywords=["MemoryError", "memory", "allocation"],
)

# --- Logic/Control Flow ---
NORMALIZE_INPUT = StrategyDefinition(
    name="normalize_input",
    description="Normalize input before processing",
    applicable_errors=[ErrorCategory.VALUE_ERROR, ErrorCategory.LOGIC_ERROR],
    priority=1.2,
    keywords=["normalize", "sanitize", "validate input"],
)

FALLBACK_DEFAULT = StrategyDefinition(
    name="fallback_default",
    description="Add fallback/default value for edge case",
    applicable_errors=[ErrorCategory.LOGIC_ERROR, ErrorCategory.VALUE_ERROR],
    priority=1.1,
    keywords=["default", "fallback", "edge case"],
)

RETURN_SHAPE_FIX = StrategyDefinition(
    name="return_shape_fix",
    description="Fix return value shape or structure",
    applicable_errors=[ErrorCategory.ASSERTION_ERROR, ErrorCategory.TYPE_ERROR],
    priority=1.1,
    keywords=["return", "shape", "structure", "expected"],
)

FIX_LOGIC_ERROR = StrategyDefinition(
    name="fix_logic_error",
    description="Generic logic fix for test failure",
    applicable_errors=[ErrorCategory.LOGIC_ERROR, ErrorCategory.ASSERTION_ERROR],
    priority=0.8,  # Lower priority - use as fallback
    keywords=["AssertionError", "assert", "expected", "actual"],
)

# --- Iteration Handling ---
FIX_ITERATION = StrategyDefinition(
    name="fix_iteration",
    description="Fix iteration-related issue",
    applicable_errors=[ErrorCategory.RUNTIME_ERROR, ErrorCategory.TYPE_ERROR],
    priority=1.2,
    keywords=["StopIteration", "iterator", "iterable", "for loop"],
)

FIX_GENERATOR = StrategyDefinition(
    name="fix_generator",
    description="Fix generator/yield issue",
    applicable_errors=[ErrorCategory.RUNTIME_ERROR],
    priority=1.0,
    keywords=["generator", "yield", "next", "exhausted"],
)


# =============================================================================
# STRATEGY REGISTRY
# =============================================================================

ALL_STRATEGIES: list[StrategyDefinition] = [
    # Null/None
    GUARD_NONE,
    NONE_COALESCE,
    # Boundary/Index
    BOUNDARY_CHECK,
    FIX_OFF_BY_ONE,
    EMPTY_CASE,
    # Type
    TYPE_CHECK,
    FIX_TYPE_COERCION,
    FIX_TYPING,
    # Dictionary/Key
    FIX_KEY_ERROR,
    USE_GET_DEFAULT,
    # Arithmetic
    FIX_DIVISION_BY_ZERO,
    FIX_OVERFLOW,
    FIX_PRECISION,
    # String
    FIX_ENCODING,
    FIX_FORMAT_STRING,
    FIX_REGEX,
    # Import/Module
    FIX_IMPORT,
    FIX_CIRCULAR_IMPORT,
    # Async/Concurrency
    FIX_AWAIT_MISSING,
    FIX_DEADLOCK,
    FIX_RACE_CONDITION,
    # Resource
    FIX_FILE_HANDLE,
    FIX_CONNECTION_LEAK,
    FIX_MEMORY,
    # Logic/Control Flow
    NORMALIZE_INPUT,
    FALLBACK_DEFAULT,
    RETURN_SHAPE_FIX,
    FIX_LOGIC_ERROR,
    # Iteration
    FIX_ITERATION,
    FIX_GENERATOR,
]

# Quick lookup by name
STRATEGY_BY_NAME: dict[str, StrategyDefinition] = {s.name: s for s in ALL_STRATEGIES}

# Default strategy names for bandit
DEFAULT_STRATEGY_NAMES: list[str] = [s.name for s in ALL_STRATEGIES]


def get_strategy(name: str) -> StrategyDefinition | None:
    """Get strategy definition by name."""
    return STRATEGY_BY_NAME.get(name)


def strategies_for_error(error_type: str) -> list[StrategyDefinition]:
    """Get strategies applicable to an error type, sorted by priority."""
    matches = [s for s in ALL_STRATEGIES if s.matches_error(error_type)]
    return sorted(matches, key=lambda s: s.priority, reverse=True)


def defensive_strategies() -> list[StrategyDefinition]:
    """Get all defensive/guard-adding strategies."""
    return [s for s in ALL_STRATEGIES if s.is_defensive]
