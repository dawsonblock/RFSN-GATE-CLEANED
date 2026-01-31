"""Complexity estimation for adaptive model selection.

Analyzes repair context to determine which LLM tier to use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ComplexityLevel(Enum):
    """Complexity tiers for model selection."""
    
    TRIVIAL = 1     # Simple syntax fixes, single-line changes
    SIMPLE = 2      # Clear bug patterns, localized fixes
    MODERATE = 3    # Multi-file changes, logic fixes
    COMPLEX = 4     # Architectural changes, deep reasoning required
    VERY_COMPLEX = 5  # Major refactoring, novel problem patterns


@dataclass
class ComplexityEstimate:
    """Result of complexity analysis."""
    
    level: ComplexityLevel
    score: float  # 0.0 to 1.0
    factors: dict[str, float]
    recommended_model_tier: str  # "fast", "standard", "reasoning"
    confidence: float
    reasoning: str


class ComplexityEstimator:
    """Estimates problem complexity from repair context.
    
    Factors considered:
    - Goal complexity (keywords analysis)
    - Codebase size
    - Historical success rate
    - Error pattern familiarity
    - Number of failing tests
    - File sprawl (changes across many files)
    """
    
    # Keywords that increase complexity
    COMPLEX_KEYWORDS = {
        "refactor": 0.2,
        "redesign": 0.3,
        "architecture": 0.3,
        "performance": 0.15,
        "security": 0.2,
        "concurrency": 0.25,
        "async": 0.15,
        "database": 0.15,
        "migration": 0.2,
    }
    
    SIMPLE_KEYWORDS = {
        "typo": -0.2,
        "import": -0.15,
        "syntax": -0.15,
        "missing": -0.1,
        "test": -0.1,
    }
    
    def __init__(self, memory_adapter: Any = None):
        """Initialize estimator.
        
        Args:
            memory_adapter: Optional memory adapter for historical queries
        """
        self.memory = memory_adapter
    
    def estimate(self, goal: str, context: dict) -> ComplexityEstimate:
        """Estimate complexity of a repair goal.
        
        Args:
            goal: The repair goal description
            context: Context dict with keys:
                - files_count: Number of files in repo
                - failing_tests: List of failing test names
                - error_type: Type of error (e.g., "TypeError")
                - touched_files: List of files likely needing changes
                - similar_success_rate: Historical success rate
        
        Returns:
            ComplexityEstimate with level and model recommendation
        """
        factors = {}
        
        # Factor 1: Goal keyword analysis
        factors["keywords"] = self._analyze_keywords(goal)
        
        # Factor 2: Codebase size
        files_count = context.get("files_count", 0)
        factors["codebase_size"] = self._score_codebase_size(files_count)
        
        # Factor 3: Number of failing tests
        failing_tests = context.get("failing_tests", [])
        factors["test_failures"] = self._score_test_failures(len(failing_tests))
        
        # Factor 4: File sprawl
        touched_files = context.get("touched_files", [])
        factors["file_sprawl"] = self._score_file_sprawl(len(touched_files))
        
        # Factor 5: Error pattern familiarity
        error_type = context.get("error_type", "")
        factors["error_familiarity"] = self._score_error_familiarity(error_type)
        
        # Factor 6: Historical success rate (if available)
        if self.memory:
            similar_rate = self._query_historical_success(context)
            factors["history"] = 1.0 - similar_rate  # Higher = harder
        else:
            factors["history"] = 0.5  # Neutral without history
        
        # Calculate weighted score
        weights = {
            "keywords": 0.25,
            "codebase_size": 0.15,
            "test_failures": 0.15,
            "file_sprawl": 0.15,
            "error_familiarity": 0.15,
            "history": 0.15,
        }
        
        score = sum(factors[k] * weights[k] for k in factors)
        score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
        
        # Map score to level
        level = self._score_to_level(score)
        
        # Determine model tier
        model_tier = self._level_to_model_tier(level)
        
        # Build reasoning
        reasoning = self._build_reasoning(factors, level)
        
        logger.info(
            "complexity_estimated",
            extra={
                "goal": goal[:100],
                "level": level.name,
                "score": round(score, 3),
                "model_tier": model_tier,
            },
        )
        
        return ComplexityEstimate(
            level=level,
            score=score,
            factors=factors,
            recommended_model_tier=model_tier,
            confidence=0.7 + (0.3 * factors.get("history", 0.5)),
            reasoning=reasoning,
        )
    
    def _analyze_keywords(self, goal: str) -> float:
        """Analyze goal for complexity keywords."""
        goal_lower = goal.lower()
        score = 0.5  # Base score
        
        for keyword, weight in self.COMPLEX_KEYWORDS.items():
            if keyword in goal_lower:
                score += weight
        
        for keyword, weight in self.SIMPLE_KEYWORDS.items():
            if keyword in goal_lower:
                score += weight  # weight is negative
        
        return max(0.0, min(1.0, score))
    
    def _score_codebase_size(self, files_count: int) -> float:
        """Score based on codebase size."""
        if files_count < 20:
            return 0.1
        elif files_count < 50:
            return 0.3
        elif files_count < 100:
            return 0.5
        elif files_count < 500:
            return 0.7
        else:
            return 0.9
    
    def _score_test_failures(self, failure_count: int) -> float:
        """Score based on number of failing tests."""
        if failure_count <= 1:
            return 0.1
        elif failure_count <= 3:
            return 0.3
        elif failure_count <= 10:
            return 0.5
        elif failure_count <= 50:
            return 0.7
        else:
            return 0.9
    
    def _score_file_sprawl(self, touched_files_count: int) -> float:
        """Score based on how many files need changes."""
        if touched_files_count <= 1:
            return 0.1
        elif touched_files_count <= 3:
            return 0.3
        elif touched_files_count <= 5:
            return 0.5
        elif touched_files_count <= 10:
            return 0.7
        else:
            return 0.9
    
    def _score_error_familiarity(self, error_type: str) -> float:
        """Score based on error pattern familiarity."""
        # Common, well-understood errors
        familiar_errors = {
            "TypeError", "AttributeError", "KeyError", "IndexError",
            "NameError", "ImportError", "ValueError", "ZeroDivisionError",
        }
        
        if error_type in familiar_errors:
            return 0.2  # Low complexity
        elif error_type:
            return 0.5  # Unknown error type
        else:
            return 0.3  # No specific error
    
    def _query_historical_success(self, context: dict) -> float:
        """Query memory for historical success rate."""
        try:
            if hasattr(self.memory, "query_success_rate"):
                return self.memory.query_success_rate(context)
        except Exception:
            pass
        return 0.5  # Neutral
    
    def _score_to_level(self, score: float) -> ComplexityLevel:
        """Map score to complexity level."""
        if score < 0.2:
            return ComplexityLevel.TRIVIAL
        elif score < 0.4:
            return ComplexityLevel.SIMPLE
        elif score < 0.6:
            return ComplexityLevel.MODERATE
        elif score < 0.8:
            return ComplexityLevel.COMPLEX
        else:
            return ComplexityLevel.VERY_COMPLEX
    
    def _level_to_model_tier(self, level: ComplexityLevel) -> str:
        """Map complexity level to model tier."""
        if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE):
            return "fast"
        elif level == ComplexityLevel.MODERATE:
            return "standard"
        else:
            return "reasoning"
    
    def _build_reasoning(self, factors: dict, level: ComplexityLevel) -> str:
        """Build human-readable reasoning for the estimate."""
        parts = []
        
        if factors["keywords"] > 0.6:
            parts.append("Goal contains complex keywords")
        elif factors["keywords"] < 0.3:
            parts.append("Goal appears straightforward")
        
        if factors["codebase_size"] > 0.5:
            parts.append("Large codebase")
        
        if factors["test_failures"] > 0.5:
            parts.append("Many failing tests")
        
        if factors["file_sprawl"] > 0.5:
            parts.append("Changes span multiple files")
        
        if factors["error_familiarity"] < 0.3:
            parts.append("Familiar error pattern")
        
        if not parts:
            parts.append("Standard complexity indicators")
        
        return f"{level.name}: " + "; ".join(parts)
