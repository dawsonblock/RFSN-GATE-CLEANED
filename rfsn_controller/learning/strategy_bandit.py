"""Strategy Bandit for Learning.

A lightweight contextual bandit for selecting patch strategies
based on failure fingerprints.

This bandit operates in PROPOSAL SPACE ONLY:
- It suggests which strategy to try
- It does NOT execute anything
- It does NOT modify gates

Arms = Strategy IDs (not patches)
Context = Failure fingerprint  
Reward = Verified success, penalized for regressions
"""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StrategyStats:
    """Statistics for a single strategy arm."""
    
    wins: int = 0
    tries: int = 0
    regressions: int = 0
    total_reward: float = 0.0
    
    # Beta distribution parameters for Thompson Sampling
    alpha: float = 1.0
    beta: float = 1.0
    
    @property
    def success_rate(self) -> float:
        """Success rate (wins / tries)."""
        if self.tries == 0:
            return 0.0
        return self.wins / self.tries
    
    @property
    def mean_reward(self) -> float:
        """Mean of Beta posterior."""
        return self.alpha / (self.alpha + self.beta)
    
    def sample(self) -> float:
        """Draw from Beta posterior (Thompson Sampling)."""
        return random.betavariate(self.alpha, self.beta)
    
    def ucb(self, total_pulls: int, c: float = 2.0) -> float:
        """Upper confidence bound score."""
        if self.tries == 0:
            return float("inf")
        import math
        exploitation = self.mean_reward
        exploration = c * math.sqrt(math.log(total_pulls + 1) / self.tries)
        return exploitation + exploration
    
    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "wins": self.wins,
            "tries": self.tries,
            "regressions": self.regressions,
            "success_rate": round(self.success_rate, 3),
            "mean_reward": round(self.mean_reward, 3),
        }

# Default strategies the bandit can choose from
# Import from centralized strategies module
try:
    from .strategies import DEFAULT_STRATEGY_NAMES
    DEFAULT_STRATEGIES = DEFAULT_STRATEGY_NAMES
except ImportError:
    # Fallback if strategies module not available
    DEFAULT_STRATEGIES = [
        # Prompting / sampling controls (advisory)
        "temperature_0.0",
        "temperature_0.3",
        "temperature_0.7",
        "temperature_1.0",
        "prompt_minimal",
        "prompt_verbose",
        "prompt_structured",

        # Planning-level tactics
        "add_test_first",
        "fix_direct",
        "refactor_small",

        # Guard / validation patterns
        "guard_none",
        "boundary_check",
        "type_check",

        # Common fix archetypes
        "normalize_input",
        "fix_off_by_one",
        "empty_case",
        "fallback_default",
        "return_shape_fix",
        "fix_import",
        "fix_typing",
    ]


class StrategyBandit:
    """Multi-armed bandit for strategy selection.
    
    Uses Thompson Sampling with optional UCB fallback.
    Operates independently per fingerprint context.
    
    Usage:
        bandit = StrategyBandit()
        
        # Get strategy suggestion
        strategy = bandit.select(fingerprint_hash, exclude=quarantined)
        
        # Update after outcome
        bandit.update(fingerprint_hash, strategy, success=True)
    """
    
    def __init__(
        self,
        strategies: list[str] | None = None,
        exploration_bonus: float = 0.1,
        db_path: str | None = None,
    ):
        """Initialize bandit.
        
        Args:
            strategies: List of strategy names. Uses defaults if None.
            exploration_bonus: Bonus for underexplored arms.
            db_path: Optional SQLite path for persistent learning.
        """
        self.strategies = set(strategies or DEFAULT_STRATEGIES)
        self.exploration_bonus = exploration_bonus
        
        # Per-context arm statistics
        # context_key -> strategy -> stats
        self._arms: dict[str, dict[str, StrategyStats]] = {}
        
        # Global statistics (across all contexts)
        self._global_stats: dict[str, StrategyStats] = {
            s: StrategyStats() for s in self.strategies
        }
        
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
        """Initialize SQLite schema for persistence."""
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_bandit (
                context_key TEXT NOT NULL,
                strategy TEXT NOT NULL,
                tries INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                regressions INTEGER NOT NULL,
                alpha REAL NOT NULL,
                beta REAL NOT NULL,
                total_reward REAL NOT NULL,
                updated_ts INTEGER NOT NULL,
                PRIMARY KEY (context_key, strategy)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_bandit_global (
                strategy TEXT PRIMARY KEY,
                tries INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                regressions INTEGER NOT NULL,
                alpha REAL NOT NULL,
                beta REAL NOT NULL,
                total_reward REAL NOT NULL,
                updated_ts INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def _load_from_db(self) -> None:
        """Load persisted stats from database."""
        if not self._conn:
            return

        # Load global stats
        cur = self._conn.execute(
            "SELECT strategy, tries, wins, regressions, alpha, beta, total_reward "
            "FROM strategy_bandit_global"
        )
        for (s, tries, wins, reg, a, b, tr) in cur.fetchall():
            if s not in self.strategies:
                continue
            st = self._global_stats.get(s) or StrategyStats()
            st.tries = int(tries)
            st.wins = int(wins)
            st.regressions = int(reg)
            st.alpha = float(a)
            st.beta = float(b)
            st.total_reward = float(tr)
            self._global_stats[s] = st

        # Load per-context stats
        cur = self._conn.execute(
            "SELECT context_key, strategy, tries, wins, regressions, alpha, beta, total_reward "
            "FROM strategy_bandit"
        )
        for (ctx, s, tries, wins, reg, a, b, tr) in cur.fetchall():
            if s not in self.strategies:
                continue
            arms = self._get_context_arms(ctx)
            st = arms.get(s) or StrategyStats()
            st.tries = int(tries)
            st.wins = int(wins)
            st.regressions = int(reg)
            st.alpha = float(a)
            st.beta = float(b)
            st.total_reward = float(tr)
            arms[s] = st

    def _persist_one(self, context_key: str, strategy: str, stats: StrategyStats) -> None:
        """Persist stats for one context/strategy pair."""
        if not self._conn:
            return
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO strategy_bandit
                (context_key, strategy, tries, wins, regressions, alpha, beta, total_reward, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(context_key, strategy) DO UPDATE SET
                tries=excluded.tries,
                wins=excluded.wins,
                regressions=excluded.regressions,
                alpha=excluded.alpha,
                beta=excluded.beta,
                total_reward=excluded.total_reward,
                updated_ts=excluded.updated_ts
            """,
            (
                context_key,
                strategy,
                stats.tries,
                stats.wins,
                stats.regressions,
                stats.alpha,
                stats.beta,
                stats.total_reward,
                now,
            ),
        )

    def _persist_global(self, strategy: str, stats: StrategyStats) -> None:
        """Persist global stats for a strategy."""
        if not self._conn:
            return
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO strategy_bandit_global
                (strategy, tries, wins, regressions, alpha, beta, total_reward, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy) DO UPDATE SET
                tries=excluded.tries,
                wins=excluded.wins,
                regressions=excluded.regressions,
                alpha=excluded.alpha,
                beta=excluded.beta,
                total_reward=excluded.total_reward,
                updated_ts=excluded.updated_ts
            """,
            (
                strategy,
                stats.tries,
                stats.wins,
                stats.regressions,
                stats.alpha,
                stats.beta,
                stats.total_reward,
                now,
            ),
        )
    
    def _get_context_arms(self, context_key: str) -> dict[str, StrategyStats]:
        """Get or create arm stats for a context."""
        if context_key not in self._arms:
            self._arms[context_key] = {
                s: StrategyStats() for s in self.strategies
            }
        return self._arms[context_key]
    
    def select(
        self,
        context_key: str,
        exclude: set[str] | None = None,
        method: str = "thompson",
    ) -> str:
        """Select a strategy for the given context.
        
        Args:
            context_key: Fingerprint hash or context identifier.
            exclude: Strategy names to exclude (e.g., quarantined).
            method: Selection method ("thompson", "ucb", "epsilon_greedy").
            
        Returns:
            Selected strategy name.
        """
        arms = self._get_context_arms(context_key)
        exclude = exclude or set()
        
        candidates = [s for s in self.strategies if s not in exclude]
        if not candidates:
            # All excluded, fall back to global best
            logger.warning("All strategies excluded, using global best")
            candidates = list(self.strategies)
        
        # Check for unexplored arms
        unexplored = [s for s in candidates if arms[s].tries == 0]
        if unexplored:
            choice = random.choice(unexplored)
            logger.debug("Selecting unexplored strategy: %s", choice)
            return choice
        
        if method == "thompson":
            # Thompson Sampling
            best_score = -1.0
            best_strategy = candidates[0]
            for s in candidates:
                score = arms[s].sample()
                if score > best_score:
                    best_score = score
                    best_strategy = s
            return best_strategy
        
        elif method == "ucb":
            # UCB selection
            total_pulls = sum(arms[s].tries for s in self.strategies)
            best_score = -1.0
            best_strategy = candidates[0]
            for s in candidates:
                score = arms[s].ucb(total_pulls)
                if score > best_score:
                    best_score = score
                    best_strategy = s
            return best_strategy
        
        else:  # epsilon_greedy
            if random.random() < self.exploration_bonus:
                return random.choice(candidates)
            # Greedy
            return max(candidates, key=lambda s: arms[s].mean_reward)
    
    def update(
        self,
        context_key: str,
        strategy: str,
        success: bool,
        regression: bool = False,
        partial_reward: float | None = None,
    ) -> None:
        """Update arm after observing outcome.
        
        Args:
            context_key: Fingerprint hash.
            strategy: Strategy that was used.
            success: Whether the strategy succeeded.
            regression: Whether the strategy caused a regression.
            partial_reward: Optional partial reward (0-1).
        """
        if strategy not in self.strategies:
            logger.warning("Unknown strategy: %s", strategy)
            return
        
        arms = self._get_context_arms(context_key)
        stats = arms[strategy]
        global_stats = self._global_stats[strategy]
        
        stats.tries += 1
        global_stats.tries += 1
        
        if success:
            stats.wins += 1
            global_stats.wins += 1
            reward = 1.0
        elif regression:
            stats.regressions += 1
            global_stats.regressions += 1
            reward = -0.5  # Penalty for regressions
        else:
            reward = partial_reward if partial_reward is not None else 0.0
        
        # Update Beta distribution
        if reward > 0:
            stats.alpha += reward
            global_stats.alpha += reward
        else:
            stats.beta += abs(reward)
            global_stats.beta += abs(reward)
        
        stats.total_reward += reward
        global_stats.total_reward += reward
        
        logger.debug(
            "Updated %s for context %s: success=%s, new_mean=%.3f",
            strategy, context_key[:8], success, stats.mean_reward
        )
        
        # Persist to database
        if self._conn:
            try:
                self._persist_one(context_key, strategy, stats)
                self._persist_global(strategy, global_stats)
                self._conn.commit()
            except Exception:
                logger.exception("Failed to persist strategy bandit stats")
    
    def get_stats(self, context_key: str | None = None) -> dict[str, dict]:
        """Get statistics for arms.
        
        Args:
            context_key: If provided, get stats for that context.
                        Otherwise, get global stats.
                        
        Returns:
            Dict of strategy name -> stats dict.
        """
        if context_key:
            arms = self._get_context_arms(context_key)
            return {s: arms[s].to_dict() for s in self.strategies}
        return {s: self._global_stats[s].to_dict() for s in self.strategies}
    
    def get_best_strategy(self, context_key: str) -> str:
        """Get the current best strategy for a context.
        
        Args:
            context_key: Fingerprint hash.
            
        Returns:
            Strategy with highest success rate.
        """
        arms = self._get_context_arms(context_key)
        return max(self.strategies, key=lambda s: arms[s].mean_reward)
    
    def register_strategy(self, strategy: str) -> None:
        """Register a new strategy.
        
        Args:
            strategy: Strategy name to add.
        """
        if strategy not in self.strategies:
            self.strategies.add(strategy)
            self._global_stats[strategy] = StrategyStats()
            logger.info("Registered new strategy: %s", strategy)
