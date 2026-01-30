"""Localization types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class LocalizationHit:
    """A localized file/span with evidence."""
    
    file: str
    span: Tuple[int, int]  # (start_line, end_line)
    score: float  # 0.0 to 1.0
    evidence_type: str  # trace, grep, embed
    evidence_text: str
    why: str  # Human-readable explanation
    
    # Metadata
    snippet: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
