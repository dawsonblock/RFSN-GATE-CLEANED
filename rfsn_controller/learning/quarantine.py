"""Quarantine Lane - Anti-regression Safety.

Quarantines strategies that have insufficient evidence of safety
or have recently caused regressions.

When a strategy is quarantined:
- It is excluded from automatic selection
- Requires higher evidence threshold to use
- May require human approval for high-risk repos

This is a SAFETY mechanism that prevents learning from
making the agent worse over time.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QuarantineStats:
    """Statistics for quarantine decisions."""
    
    strategy: str
    total_tries: int = 0
    successes: int = 0
    regressions: int = 0
    last_regression_timestamp: float | None = None
    
    @property
    def success_rate(self) -> float:
        if self.total_tries == 0:
            return 0.0
        return self.successes / self.total_tries
    
    @property
    def regression_rate(self) -> float:
        if self.total_tries == 0:
            return 0.0
        return self.regressions / self.total_tries


@dataclass
class QuarantineConfig:
    """Configuration for quarantine thresholds."""
    
    # Minimum successes required to be trusted
    min_successes: int = 2
    
    # Maximum regression rate before quarantine
    max_regression_rate: float = 0.3
    
    # Recent regression cooldown (seconds)
    regression_cooldown: float = 3600.0  # 1 hour
    
    # Minimum tries before applying regression rate check
    min_tries_for_rate: int = 5


def is_quarantined(
    stats: dict[str, Any],
    config: QuarantineConfig | None = None,
) -> bool:
    """Check if a strategy should be quarantined.
    
    Args:
        stats: Strategy statistics dict with "wins", "tries", "regressions".
        config: Quarantine configuration.
        
    Returns:
        True if strategy should be quarantined.
    """
    config = config or QuarantineConfig()
    
    tries = stats.get("tries", 0)
    wins = stats.get("wins", 0)
    regressions = stats.get("regressions", 0)
    
    # Not enough evidence yet
    if tries < config.min_successes:
        return True
    
    # Zero wins is always quarantined
    if wins == 0:
        return True
    
    # Check regression rate
    if tries >= config.min_tries_for_rate:
        regression_rate = regressions / tries
        if regression_rate > config.max_regression_rate:
            return True
    
    return False


class QuarantineLane:
    """Manager for quarantined strategies.
    
    Tracks which strategies are quarantined and why.
    Provides methods to check and update quarantine status.
    
    Usage:
        lane = QuarantineLane()
        
        # Check if quarantined
        if lane.is_quarantined("temperature_1.0", context="abc123"):
            excluded.add("temperature_1.0")
        
        # Update based on outcome
        lane.record_outcome("temperature_0.3", context="abc123", success=True)
    """
    
    def __init__(
        self,
        config: QuarantineConfig | None = None,
        db_path: str | None = None,
    ):
        """Initialize quarantine lane.
        
        Args:
            config: Quarantine configuration.
            db_path: Optional SQLite path for persistent quarantine.
        """
        self.config = config or QuarantineConfig()
        
        # Per-context quarantine status
        # context -> strategy -> QuarantineStats
        self._stats: dict[str, dict[str, QuarantineStats]] = {}
        
        # Globally quarantined strategies (across all contexts)
        self._global_quarantine: set[str] = set()
        
        # SQLite persistence
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        if self._db_path:
            parent = os.path.dirname(os.path.abspath(self._db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._init_schema()
            self._load_from_db()
    
    def _init_schema(self) -> None:
        """Initialize SQLite schema for quarantine persistence."""
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantine_stats (
                context TEXT NOT NULL,
                strategy TEXT NOT NULL,
                total_tries INTEGER NOT NULL,
                successes INTEGER NOT NULL,
                regressions INTEGER NOT NULL,
                last_regression_ts REAL,
                updated_ts INTEGER NOT NULL,
                PRIMARY KEY (context, strategy)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantine_global (
                strategy TEXT PRIMARY KEY,
                reason TEXT,
                quarantined_ts INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def _load_from_db(self) -> None:
        """Load persisted quarantine stats from database."""
        if not self._conn:
            return

        # Load per-context stats
        cur = self._conn.execute(
            "SELECT context, strategy, total_tries, successes, regressions, last_regression_ts "
            "FROM quarantine_stats"
        )
        for (ctx, s, tries, succ, reg, last_ts) in cur.fetchall():
            if ctx not in self._stats:
                self._stats[ctx] = {}
            self._stats[ctx][s] = QuarantineStats(
                strategy=s,
                total_tries=int(tries),
                successes=int(succ),
                regressions=int(reg),
                last_regression_timestamp=float(last_ts) if last_ts else None,
            )

        # Load global quarantine list
        cur = self._conn.execute("SELECT strategy FROM quarantine_global")
        for (s,) in cur.fetchall():
            self._global_quarantine.add(s)

    def _persist_stats(self, context: str, strategy: str, stats: QuarantineStats) -> None:
        """Persist stats for one context/strategy pair."""
        if not self._conn:
            return
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO quarantine_stats
                (context, strategy, total_tries, successes, regressions, last_regression_ts, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(context, strategy) DO UPDATE SET
                total_tries=excluded.total_tries,
                successes=excluded.successes,
                regressions=excluded.regressions,
                last_regression_ts=excluded.last_regression_ts,
                updated_ts=excluded.updated_ts
            """,
            (
                context,
                strategy,
                stats.total_tries,
                stats.successes,
                stats.regressions,
                stats.last_regression_timestamp,
                now,
            ),
        )
        self._conn.commit()
    
    def _get_stats(self, context: str, strategy: str) -> QuarantineStats:
        """Get or create stats for a context/strategy pair."""
        if context not in self._stats:
            self._stats[context] = {}
        if strategy not in self._stats[context]:
            self._stats[context][strategy] = QuarantineStats(strategy=strategy)
        return self._stats[context][strategy]
    
    def is_quarantined(
        self,
        strategy: str,
        context: str | None = None,
    ) -> bool:
        """Check if a strategy is quarantined.
        
        Args:
            strategy: Strategy name.
            context: Optional context key.
            
        Returns:
            True if strategy should not be used.
        """
        # Check global quarantine first
        if strategy in self._global_quarantine:
            return True
        
        # Check context-specific quarantine
        if context and context in self._stats:
            stats = self._stats[context].get(strategy)
            if stats:
                return is_quarantined(
                    {
                        "tries": stats.total_tries,
                        "wins": stats.successes,
                        "regressions": stats.regressions,
                    },
                    self.config,
                )
        
        return False
    
    def get_quarantined_strategies(
        self,
        context: str | None = None,
    ) -> set[str]:
        """Get all quarantined strategies.
        
        Args:
            context: Optional context to check.
            
        Returns:
            Set of quarantined strategy names.
        """
        result = self._global_quarantine.copy()
        
        if context and context in self._stats:
            for strategy, stats in self._stats[context].items():
                if is_quarantined(
                    {
                        "tries": stats.total_tries,
                        "wins": stats.successes,
                        "regressions": stats.regressions,
                    },
                    self.config,
                ):
                    result.add(strategy)
        
        return result
    
    def record_outcome(
        self,
        strategy: str,
        context: str,
        success: bool,
        regression: bool = False,
        timestamp: float | None = None,
    ) -> bool:
        """Record outcome and update quarantine status.
        
        Args:
            strategy: Strategy used.
            context: Context key.
            success: Whether strategy succeeded.
            regression: Whether strategy caused regression.
            timestamp: Optional timestamp.
            
        Returns:
            True if strategy became quarantined due to this outcome.
        """
        timestamp = timestamp or time.time()
        
        stats = self._get_stats(context, strategy)
        was_quarantined = self.is_quarantined(strategy, context)
        
        stats.total_tries += 1
        if success:
            stats.successes += 1
        if regression:
            stats.regressions += 1
            stats.last_regression_timestamp = timestamp
        
        now_quarantined = self.is_quarantined(strategy, context)
        
        if now_quarantined and not was_quarantined:
            logger.warning(
                "Strategy %s quarantined for context %s: "
                "tries=%d, wins=%d, regressions=%d",
                strategy, context[:8],
                stats.total_tries, stats.successes, stats.regressions
            )
        
        # Persist to database
        if self._conn:
            try:
                self._persist_stats(context, strategy, stats)
            except Exception:
                logger.exception("Failed to persist quarantine stats")
        
        return now_quarantined and not was_quarantined
    
    def force_quarantine(self, strategy: str, reason: str = "manual") -> None:
        """Force-quarantine a strategy globally.
        
        Args:
            strategy: Strategy to quarantine.
            reason: Reason for quarantine.
        """
        logger.info("Force-quarantining strategy %s: %s", strategy, reason)
        self._global_quarantine.add(strategy)
    
    def release_from_quarantine(self, strategy: str) -> None:
        """Remove a strategy from global quarantine.
        
        Args:
            strategy: Strategy to release.
        """
        if strategy in self._global_quarantine:
            logger.info("Releasing strategy %s from quarantine", strategy)
            self._global_quarantine.discard(strategy)
    
    def get_stats_summary(self, context: str | None = None) -> list[dict]:
        """Get quarantine stats summary.
        
        Args:
            context: Optional context to summarize.
            
        Returns:
            List of stats dicts.
        """
        if context and context in self._stats:
            return [
                {
                    "strategy": s.strategy,
                    "tries": s.total_tries,
                    "successes": s.successes,
                    "regressions": s.regressions,
                    "quarantined": self.is_quarantined(s.strategy, context),
                }
                for s in self._stats[context].values()
            ]
        return []
