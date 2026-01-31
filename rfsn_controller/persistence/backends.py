"""Persistence backends for learning data storage.

Provides pluggable backends for storing bandit statistics and quarantine data:
- SQLiteBackend: Local SQLite database (default)
- PostgreSQLBackend: Production PostgreSQL database
- MemoryBackend: In-memory storage for testing
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KeyValue:
    """Generic key-value pair for storage."""
    
    key: str
    value: dict
    updated_at: float


class Backend(ABC):
    """Abstract base class for persistence backends."""
    
    @abstractmethod
    def get(self, table: str, key: str) -> dict | None:
        """Get a value by key from a table."""
        ...
    
    @abstractmethod
    def set(self, table: str, key: str, value: dict) -> None:
        """Set a value by key in a table."""
        ...
    
    @abstractmethod
    def delete(self, table: str, key: str) -> bool:
        """Delete a value by key from a table."""
        ...
    
    @abstractmethod
    def list_keys(self, table: str) -> list[str]:
        """List all keys in a table."""
        ...
    
    @abstractmethod
    def list_all(self, table: str) -> list[KeyValue]:
        """List all key-value pairs in a table."""
        ...
    
    @abstractmethod
    def clear(self, table: str) -> None:
        """Clear all entries in a table."""
        ...
    
    def close(self) -> None:
        """Close the backend connection."""
        pass


class MemoryBackend(Backend):
    """In-memory backend for testing."""
    
    def __init__(self):
        self._data: dict[str, dict[str, dict]] = {}
    
    def get(self, table: str, key: str) -> dict | None:
        return self._data.get(table, {}).get(key)
    
    def set(self, table: str, key: str, value: dict) -> None:
        if table not in self._data:
            self._data[table] = {}
        self._data[table][key] = value
    
    def delete(self, table: str, key: str) -> bool:
        if table in self._data and key in self._data[table]:
            del self._data[table][key]
            return True
        return False
    
    def list_keys(self, table: str) -> list[str]:
        return list(self._data.get(table, {}).keys())
    
    def list_all(self, table: str) -> list[KeyValue]:
        import time
        return [
            KeyValue(key=k, value=v, updated_at=time.time())
            for k, v in self._data.get(table, {}).items()
        ]
    
    def clear(self, table: str) -> None:
        if table in self._data:
            self._data[table] = {}


class SQLiteBackend(Backend):
    """SQLite backend for local persistence."""
    
    def __init__(self, db_path: str):
        import os
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()
    
    def _init_schema(self) -> None:
        """Initialize the database schema."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                table_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (table_name, key)
            )
        """)
        self._conn.commit()
    
    def get(self, table: str, key: str) -> dict | None:
        import json
        cursor = self._conn.execute(
            "SELECT value FROM kv_store WHERE table_name = ? AND key = ?",
            (table, key),
        )
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
    
    def set(self, table: str, key: str, value: dict) -> None:
        import json
        import time
        self._conn.execute(
            """
            INSERT OR REPLACE INTO kv_store (table_name, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (table, key, json.dumps(value), time.time()),
        )
        self._conn.commit()
    
    def delete(self, table: str, key: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM kv_store WHERE table_name = ? AND key = ?",
            (table, key),
        )
        self._conn.commit()
        return cursor.rowcount > 0
    
    def list_keys(self, table: str) -> list[str]:
        cursor = self._conn.execute(
            "SELECT key FROM kv_store WHERE table_name = ?",
            (table,),
        )
        return [row[0] for row in cursor.fetchall()]
    
    def list_all(self, table: str) -> list[KeyValue]:
        import json
        cursor = self._conn.execute(
            "SELECT key, value, updated_at FROM kv_store WHERE table_name = ?",
            (table,),
        )
        return [
            KeyValue(key=row[0], value=json.loads(row[1]), updated_at=row[2])
            for row in cursor.fetchall()
        ]
    
    def clear(self, table: str) -> None:
        self._conn.execute(
            "DELETE FROM kv_store WHERE table_name = ?",
            (table,),
        )
        self._conn.commit()
    
    def close(self) -> None:
        self._conn.close()


class PostgreSQLBackend(Backend):
    """PostgreSQL backend for production persistence.
    
    Requires psycopg2-binary package.
    Connection string format: postgresql://user:password@host:port/database
    """
    
    def __init__(self, connection_string: str):
        try:
            import psycopg2
            self._conn = psycopg2.connect(connection_string)
            self._init_schema()
        except ImportError as e:
            raise ImportError(
                "psycopg2-binary is required for PostgreSQL. "
                "Install with: pip install 'rfsn-controller[postgres]'"
            ) from e
    
    def _init_schema(self) -> None:
        """Initialize the database schema."""
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    table_name TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value JSONB NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (table_name, key)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_kv_table_name 
                ON kv_store (table_name)
            """)
        self._conn.commit()
    
    def get(self, table: str, key: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM kv_store WHERE table_name = %s AND key = %s",
                (table, key),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        return None
    
    def set(self, table: str, key: str, value: dict) -> None:
        import json
        import time
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kv_store (table_name, key, value, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (table_name, key) 
                DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (table, key, json.dumps(value), time.time()),
            )
        self._conn.commit()
    
    def delete(self, table: str, key: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kv_store WHERE table_name = %s AND key = %s",
                (table, key),
            )
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted
    
    def list_keys(self, table: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT key FROM kv_store WHERE table_name = %s",
                (table,),
            )
            return [row[0] for row in cur.fetchall()]
    
    def list_all(self, table: str) -> list[KeyValue]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT key, value, updated_at FROM kv_store WHERE table_name = %s",
                (table,),
            )
            return [
                KeyValue(key=row[0], value=row[1], updated_at=row[2])
                for row in cur.fetchall()
            ]
    
    def clear(self, table: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kv_store WHERE table_name = %s",
                (table,),
            )
        self._conn.commit()
    
    def close(self) -> None:
        self._conn.close()


def create_backend(
    backend_type: str = "sqlite",
    **kwargs: Any,
) -> Backend:
    """Factory function to create a persistence backend.
    
    Args:
        backend_type: One of "sqlite", "postgres", "memory"
        **kwargs: Backend-specific arguments:
            - sqlite: db_path (str)
            - postgres: connection_string (str)
            - memory: (none)
    
    Returns:
        Configured Backend instance
        
    Examples:
        # SQLite (default)
        backend = create_backend("sqlite", db_path="./learning.db")
        
        # PostgreSQL
        backend = create_backend(
            "postgres",
            connection_string="postgresql://user:pass@localhost/rfsn"
        )
        
        # Memory (testing)
        backend = create_backend("memory")
    """
    if backend_type == "sqlite":
        db_path = kwargs.get("db_path", "./rfsn_learning.db")
        return SQLiteBackend(db_path)
    elif backend_type in ("postgres", "postgresql"):
        connection_string = kwargs.get("connection_string")
        if not connection_string:
            raise ValueError("PostgreSQL requires connection_string")
        return PostgreSQLBackend(connection_string)
    elif backend_type == "memory":
        return MemoryBackend()
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")
