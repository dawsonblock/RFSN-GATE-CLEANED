"""
from __future__ import annotations
RFSN Planner v5 - SWE-bench Optimized Coding Planner

A proposal-only coding planner that operates under strict RFSN authority model.
Never executes code, never bypasses safety, only generates structured proposals.

Key Principles:
- Untrusted by design
- Serial execution only
- Evidence-driven proposals
- Gate-first architecture
- Minimal verifiable changes

Architecture:
- ProposalPlanner: Generates individual proposals
- MetaPlanner: Strategy layer above proposal generation
- ScoringEngine: Evaluates proposal quality
- StateTracker: Maintains planning state
"""

from .proposal import Proposal, ProposalIntent, ActionType, ExpectedEffect, RiskLevel, Target, TestExpectation
from .planner import ProposalPlanner
from .meta_planner import MetaPlanner, PlannerState
from .scoring import ScoringEngine, CandidateScore
from .state_tracker import StateTracker, HypothesisOutcome, GateRejectionType

__version__ = "5.0.0"

__all__ = [
    # Core types
    "Proposal",
    "ProposalIntent",
    "ActionType",
    "ExpectedEffect",
    "RiskLevel",
    "Target",
    "TestExpectation",
    # Planners
    "ProposalPlanner",
    "MetaPlanner",
    "PlannerState",
    # Scoring
    "ScoringEngine",
    "CandidateScore",
    # State tracking
    "StateTracker",
    "HypothesisOutcome",
    "GateRejectionType",
]
