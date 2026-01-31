"""Persistence layer for RFSN Controller.

Provides pluggable backend implementations for learning data storage:
- SQLite (default, local development)
- PostgreSQL (production)
- Memory (testing)
"""

from __future__ import annotations

from .backends import (
    Backend,
    MemoryBackend,
    PostgreSQLBackend,
    SQLiteBackend,
    create_backend,
)

__all__ = [
    "Backend",
    "SQLiteBackend",
    "PostgreSQLBackend",
    "MemoryBackend",
    "create_backend",
]
