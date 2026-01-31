"""Meta-Planner for RFSN v5.

Strategic layer above proposal generation. Decides which proposal to ask for
next and maintains structured state across attempts.

Does not execute code - only chooses strategies and delegates to ProposalPlanner.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .planner import ProposalPlanner
from .proposal import Proposal
from .scoring import ScoringEngine
from .state_tracker import GateRejectionType, HypothesisOutcome, StateTracker

if TYPE_CHECKING:
    from ..learning import LearnedStrategySelector

logger = logging.getLogger(__name__)


class PlannerPhase(Enum):
    """Current phase of the planning loop."""

    REPRODUCE = "reproduce"  # Establish reproduction
    LOCALIZE = "localize"  # Find the fault
    PATCH = "patch"  # Apply fix
    VERIFY = "verify"  # Confirm fix works
    EXPAND = "expand"  # Test for regressions
    STUCK = "stuck"  # Cannot proceed safely


@dataclass
class PlannerState:
    """High-level planner state."""

    phase: PlannerPhase = PlannerPhase.REPRODUCE
    last_proposal: Proposal | None = None
    last_outcome: HypothesisOutcome | None = None
    phase_attempts: int = 0  # Attempts in current phase


class MetaPlanner:
    """
    Meta-planner: strategic decision layer above proposal generation.

    Responsibilities:
    - Choose which proposal to generate next
    - Maintain phase transitions (reproduce -> localize -> patch -> verify)
    - Detect stuck states and pivot strategies
    - Handle gate rejections intelligently
    - Coordinate multi-model candidate selection

    Never executes code. Only decides strategy and delegates.
    """

    def __init__(
        self,
        state_tracker: StateTracker | None = None,
        max_phase_attempts: int = 3,
        strategy_selector: LearnedStrategySelector | None = None,
    ):
        """
        Initialize meta-planner.

        Args:
            state_tracker: State tracker instance, or creates new one
            max_phase_attempts: Max attempts per phase before pivoting
            strategy_selector: Optional learned strategy selector for bandit-guided planning
        """
        self.state_tracker = state_tracker or StateTracker()
        self.planner = ProposalPlanner(self.state_tracker)
        self.planner_state = PlannerState()
        self.max_phase_attempts = max_phase_attempts
        self.last_feedback: dict | None = None
        self.strategy_selector = strategy_selector
        self._last_recommendation = None  # Track for learning updates

    def next_proposal(
        self,
        controller_feedback: dict | None = None,
        gate_rejection: tuple[str, str] | None = None,
    ) -> Proposal:
        """
        Generate the next proposal based on state and feedback.

        Args:
            controller_feedback: Feedback from controller execution
                {
                    "success": bool,
                    "output": str,
                    "tests_passed": int,
                    "tests_failed": int,
                    "traceback": Optional[str]
                }
            gate_rejection: If proposal was rejected, (rejection_type, reason)

        Returns:
            Next proposal to submit
        """
        self.state_tracker.increment_iteration()

        # Handle gate rejection first
        if gate_rejection:
            return self._handle_gate_rejection(gate_rejection)

        # Update state from feedback
        if controller_feedback:
            self.last_feedback = controller_feedback
            self._process_feedback(controller_feedback)

        # Check if stuck
        if self.state_tracker.is_stuck():
            return self._handle_stuck()

        # Choose next action based on phase
        if self.planner_state.phase == PlannerPhase.REPRODUCE:
            return self._next_reproduce()
        elif self.planner_state.phase == PlannerPhase.LOCALIZE:
            return self._next_localize()
        elif self.planner_state.phase == PlannerPhase.PATCH:
            return self._next_patch()
        elif self.planner_state.phase == PlannerPhase.VERIFY:
            return self._next_verify()
        elif self.planner_state.phase == PlannerPhase.EXPAND:
            return self._next_expand()
        else:  # STUCK
            return self._handle_stuck()

    def _next_reproduce(self) -> Proposal:
        """Generate next proposal for reproduction phase."""
        if self.state_tracker.has_reproduction():
            # Move to localization
            self._transition_phase(PlannerPhase.LOCALIZE)
            return self._next_localize()

        # Try to reproduce
        if self.state_tracker.failing_tests:
            # We know specific failing tests
            test = list(self.state_tracker.failing_tests)[0]
            proposal = self.planner.propose_reproduce(test_nodeid=test)
        else:
            # Run broader suite to identify failures
            proposal = self.planner.propose_reproduce()

        self._record_proposal(proposal)
        return proposal

    def _next_localize(self) -> Proposal:
        """Generate next proposal for localization phase."""
        # Check if we should pivot to localization from patch failures
        if self.state_tracker.should_pivot_to_localization():
            self.planner_state.phase_attempts = 0  # Reset attempts

        # Do we have a suspect file from traceback?
        top_suspect = self.state_tracker.get_top_suspect_file()

        if top_suspect:
            # Read the suspect file
            proposal = self.planner.propose_localize_file(
                file_path=top_suspect,
                reason="File appears in failure traceback.",
            )
            self._record_proposal(proposal)
            # After localization, move to patch
            self._transition_phase(PlannerPhase.PATCH)
            return proposal

        # No suspect files yet - search for clues
        if self.state_tracker.exception_types:
            exc_type = list(self.state_tracker.exception_types)[0]
            proposal = self.planner.propose_search_repo(
                pattern=exc_type,
                reason=f"Search for {exc_type} to find relevant error handling.",
            )
            self._record_proposal(proposal)
            return proposal

        # Can't localize - need more info from reproduce
        self._transition_phase(PlannerPhase.REPRODUCE)
        return self._next_reproduce()

    def _next_patch(self) -> Proposal:
        """Generate next proposal for patch phase.
        
        Uses strategy_selector if available for learning-informed decisions.
        """
        # Check phase attempts
        if self.planner_state.phase_attempts >= self.max_phase_attempts:
            # Too many patch attempts - update learning and pivot to localization
            self._update_learning_for_failed_phase()
            self._transition_phase(PlannerPhase.LOCALIZE)
            return self._next_localize()

        # Get suspect location
        suspect_symbol = self.state_tracker.get_top_suspect_symbol()
        suspect_file = self.state_tracker.get_top_suspect_file()

        if not suspect_file:
            # Need localization first
            self._transition_phase(PlannerPhase.LOCALIZE)
            return self._next_localize()

        # Get strategy recommendation from learning layer if available
        strategy = self._get_strategy_recommendation()
        
        # Map strategy to proposal based on recommendation or exception type
        proposal = self._create_patch_proposal(suspect_file, suspect_symbol, strategy)

        self._record_proposal(proposal)
        self.planner_state.phase_attempts += 1

        # After patch, verify
        self._transition_phase(PlannerPhase.VERIFY)
        return proposal

    def _get_strategy_recommendation(self) -> str | None:
        """Get strategy recommendation from learning layer."""
        if not self.strategy_selector:
            return None
        
        try:
            # Build fingerprint context
            failing = list(self.state_tracker.failing_tests)
            traceback_str = "\n".join(
                f"{f[0]}:{f[1]}" for f in self.state_tracker.traceback_frames[:5]
            )
            
            rec = self.strategy_selector.recommend(
                failing_tests=failing,
                lint_errors=[],
                stack_trace=traceback_str if traceback_str else None,
            )
            self._last_recommendation = rec
            logger.info(
                "Strategy recommendation: %s (confidence=%.2f)",
                rec.strategy, rec.confidence
            )
            return rec.strategy
        except Exception as e:
            logger.warning("Failed to get strategy recommendation: %s", e)
            return None

    def _create_patch_proposal(
        self,
        suspect_file: str,
        suspect_symbol: tuple[str, str] | None,
        strategy: str | None,
    ) -> Proposal:
        """Create patch proposal based on strategy or exception type."""
        symbol_name = suspect_symbol[1] if suspect_symbol else "unknown"
        
        # Strategy-based proposal creation
        if strategy:
            # Guard-type strategies
            if strategy in ("guard_none", "none_check"):
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="none_check",
                    expected_behavior="Prevents AttributeError by checking for None",
                )
            elif strategy == "boundary_check":
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="boundary_check",
                    expected_behavior="Prevents IndexError by validating indices",
                )
            elif strategy == "type_check":
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="type_check",
                    expected_behavior="Prevents TypeError by validating types",
                )
            elif strategy == "fix_off_by_one":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Off-by-one error in loop or index",
                    fix_description="Adjust boundary condition by one",
                    expected_behavior="Corrects index/loop boundary",
                )
            elif strategy == "empty_case":
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="empty_check",
                    expected_behavior="Handles empty input case explicitly",
                )
            elif strategy == "normalize_input":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Input requires normalization",
                    fix_description="Normalize input before processing",
                    expected_behavior="Handles varied input formats correctly",
                )
            elif strategy == "fallback_default":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Missing fallback for edge case",
                    fix_description="Add fallback/default value",
                    expected_behavior="Returns sensible default for edge cases",
                )
            elif strategy == "return_shape_fix":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Return value shape mismatch",
                    fix_description="Fix return value shape/structure",
                    expected_behavior="Returns correctly shaped value",
                )
            elif strategy == "fix_import":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Import error or missing dependency",
                    fix_description="Fix import statement",
                    expected_behavior="Module imports correctly",
                )
            elif strategy == "fix_typing":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Type annotation or conversion error",
                    fix_description="Fix type handling",
                    expected_behavior="Correct type conversion/handling",
                )
            # --- New strategies: Dictionary/Key ---
            elif strategy == "fix_key_error":
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="key_check",
                    expected_behavior="Prevents KeyError with key existence check",
                )
            elif strategy == "use_get_default":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="KeyError from missing dictionary key",
                    fix_description="Use dict.get() with default value",
                    expected_behavior="Returns default when key missing",
                )
            # --- New strategies: Arithmetic ---
            elif strategy == "fix_division_by_zero":
                return self.planner.propose_add_guard(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    guard_type="zero_check",
                    expected_behavior="Prevents ZeroDivisionError",
                )
            elif strategy == "fix_overflow":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Numeric overflow error",
                    fix_description="Add bounds check or use larger type",
                    expected_behavior="Handles large numbers safely",
                )
            elif strategy == "fix_precision":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Floating point precision issue",
                    fix_description="Use appropriate precision handling",
                    expected_behavior="Handles floating point correctly",
                )
            # --- New strategies: String ---
            elif strategy == "fix_encoding":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="String encoding/decoding error",
                    fix_description="Fix encoding handling",
                    expected_behavior="Handles text encoding correctly",
                )
            elif strategy == "fix_format_string":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="String formatting error",
                    fix_description="Fix format string/template",
                    expected_behavior="Formats string correctly",
                )
            elif strategy == "fix_regex":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Regular expression error",
                    fix_description="Fix regex pattern",
                    expected_behavior="Pattern matches correctly",
                )
            # --- New strategies: Async ---
            elif strategy == "fix_await_missing":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Missing await keyword",
                    fix_description="Add await to coroutine call",
                    expected_behavior="Async function called correctly",
                )
            elif strategy == "fix_deadlock":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Potential deadlock in locking",
                    fix_description="Fix lock ordering or add timeout",
                    expected_behavior="Prevents deadlock condition",
                )
            elif strategy == "fix_race_condition":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Race condition detected",
                    fix_description="Add synchronization",
                    expected_behavior="Thread-safe operation",
                )
            # --- New strategies: Resource ---
            elif strategy == "fix_file_handle":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="File handle not properly closed",
                    fix_description="Use context manager or ensure close",
                    expected_behavior="File handle cleaned up properly",
                )
            elif strategy == "fix_connection_leak":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Connection/resource leak",
                    fix_description="Ensure resource cleanup",
                    expected_behavior="Resources released properly",
                )
            elif strategy == "fix_memory":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Memory allocation issue",
                    fix_description="Fix memory handling",
                    expected_behavior="Memory managed correctly",
                )
            # --- New strategies: Iteration ---
            elif strategy == "fix_iteration":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Iteration or StopIteration error",
                    fix_description="Fix iterator handling",
                    expected_behavior="Iteration completes correctly",
                )
            elif strategy == "fix_generator":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Generator/yield issue",
                    fix_description="Fix generator behavior",
                    expected_behavior="Generator yields correctly",
                )
            # --- New strategies: Null coalesce ---
            elif strategy == "none_coalesce":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="None value where value expected",
                    fix_description="Use default when None",
                    expected_behavior="Returns default for None",
                )
            elif strategy == "fix_type_coercion":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Type conversion needed",
                    fix_description="Add explicit type conversion",
                    expected_behavior="Values converted correctly",
                )
            elif strategy == "fix_circular_import":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Circular import dependency",
                    fix_description="Break circular import",
                    expected_behavior="Module imports successfully",
                )
            elif strategy == "fix_logic_error":
                return self.planner.propose_fix_logic_error(
                    file_path=suspect_file,
                    symbol=symbol_name,
                    error_description="Generic logic error",
                    fix_description="Fix logic to match expected behavior",
                    expected_behavior="Test passes",
                )
        
        # Fall back to exception-based selection
        if "AttributeError" in self.state_tracker.exception_types:
            return self.planner.propose_add_guard(
                file_path=suspect_file,
                symbol=symbol_name,
                guard_type="none_check",
                expected_behavior="Prevents AttributeError",
            )
        elif "IndexError" in self.state_tracker.exception_types:
            return self.planner.propose_add_guard(
                file_path=suspect_file,
                symbol=symbol_name,
                guard_type="boundary_check",
                expected_behavior="Prevents IndexError",
            )
        elif "KeyError" in self.state_tracker.exception_types:
            return self.planner.propose_add_guard(
                file_path=suspect_file,
                symbol=symbol_name,
                guard_type="key_check",
                expected_behavior="Prevents KeyError",
            )
        elif "ZeroDivisionError" in self.state_tracker.exception_types:
            return self.planner.propose_add_guard(
                file_path=suspect_file,
                symbol=symbol_name,
                guard_type="zero_check",
                expected_behavior="Prevents ZeroDivisionError",
            )
        elif "TypeError" in self.state_tracker.exception_types:
            return self.planner.propose_add_guard(
                file_path=suspect_file,
                symbol=symbol_name,
                guard_type="type_check",
                expected_behavior="Prevents TypeError",
            )
        else:
            # Generic logic fix
            return self.planner.propose_fix_logic_error(
                file_path=suspect_file,
                symbol=symbol_name,
                error_description="Logic error causing test failure",
                fix_description="Fix logic to match expected behavior",
                expected_behavior="Corrects behavior to satisfy test",
            )

    def _update_learning_for_failed_phase(self) -> None:
        """Update learning layer when a phase fails (too many attempts)."""
        if not self.strategy_selector or not self._last_recommendation:
            return
        try:
            self.strategy_selector.update(
                self._last_recommendation,
                success=False,
                regression=False,
                partial_reward=0.0,
            )
            logger.info("Updated learning: phase failed, strategy=%s", 
                       self._last_recommendation.strategy)
        except Exception as e:
            logger.warning("Failed to update learning: %s", e)

    def _next_verify(self) -> Proposal:
        """Generate next proposal for verification phase."""
        # Run the specific failing test
        if self.state_tracker.failing_tests:
            test = list(self.state_tracker.failing_tests)[0]
            proposal = self.planner.propose_verify_targeted(
                test_nodeid=test,
                after_fix="the fix is correctly applied",
            )
            self._record_proposal(proposal)
            # After verify, expand or go back to patch
            return proposal

        # No specific test - run broader
        proposal = self.planner.propose_expand_verification(
            test_path="tests/",
            scope="all tests",
        )
        self._record_proposal(proposal)
        return proposal

    def _next_expand(self) -> Proposal:
        """Generate next proposal for expansion phase."""
        # Run broader test suite to catch regressions
        proposal = self.planner.propose_expand_verification(
            test_path="tests/",
            scope="full test suite",
        )
        self._record_proposal(proposal)
        return proposal

    def _handle_gate_rejection(
        self, rejection: tuple[str, str]
    ) -> Proposal:
        """
        Handle gate rejection and generate recovery proposal.

        Args:
            rejection: (rejection_type, reason)

        Returns:
            Recovery proposal
        """
        rejection_type_str, reason = rejection

        # Parse rejection type
        try:
            rejection_type = GateRejectionType(rejection_type_str)
        except ValueError:
            rejection_type = GateRejectionType.UNKNOWN

        # Record rejection
        if self.planner_state.last_proposal:
            self.state_tracker.record_hypothesis(
                proposal_id=self.planner_state.last_proposal.proposal_id,
                hypothesis=self.planner_state.last_proposal.hypothesis,
                outcome=HypothesisOutcome.REJECTED_BY_GATE,
                rejection_reason=reason,
                rejection_type=rejection_type,
            )

        # Check for repeated schema violations - enter compliance mode
        recent_rejections = self.state_tracker.recent_gate_rejection_types(n=3)
        if recent_rejections.count(GateRejectionType.SCHEMA_VIOLATION) >= 2:
            # Too many schema violations - only do safe analyze actions
            return self.planner.propose_localize_file(
                file_path=".",
                reason="Entering safe mode after repeated schema violations",
            )

        # Handle specific rejection types
        if rejection_type == GateRejectionType.ORDERING_VIOLATION:
            # Wrong phase - likely tried to refactor while tests fail
            # Go back to reproduce or localize
            if not self.state_tracker.has_reproduction():
                self._transition_phase(PlannerPhase.REPRODUCE)
                return self._next_reproduce()
            else:
                self._transition_phase(PlannerPhase.LOCALIZE)
                return self._next_localize()

        elif rejection_type == GateRejectionType.BOUNDS_VIOLATION:
            # Exceeded some limit - try smaller scope
            self.planner_state.phase_attempts = 0
            self._transition_phase(PlannerPhase.LOCALIZE)
            return self._next_localize()

        elif rejection_type == GateRejectionType.INVARIANT_VIOLATION:
            # Violated safety rule - pivot to safe analyze
            return self.planner.propose_localize_file(
                file_path=".",
                reason="Entering safe mode after invariant violation",
            )

        # Generic recovery - move to safe analyze phase
        self._transition_phase(PlannerPhase.LOCALIZE)
        return self._next_localize()

    def _handle_stuck(self) -> Proposal:
        """Handle stuck state."""
        reason = "Iteration budget exceeded or stuck in failure loop."

        if self.state_tracker.consecutive_failures >= self.state_tracker.stuck_threshold:
            reason = f"Same failure pattern repeated {self.state_tracker.consecutive_failures} times. Need different approach."

        return self.planner.propose_explain_stuck(reason)

    def _process_feedback(self, feedback: dict):
        """Process controller feedback and update state."""
        # Extract info from feedback
        output = feedback.get("output", "")
        tests_failed = feedback.get("tests_failed", 0)
        tests_passed = feedback.get("tests_passed", 0)
        traceback = feedback.get("traceback")

        # Update failing tests
        if tests_failed > 0:
            test_nodeid = self.planner.parse_pytest_nodeid(output)
            if test_nodeid:
                self.state_tracker.failing_tests.add(test_nodeid)

        # Update exception types
        if traceback:
            exc_type = self.planner.extract_exception_type(traceback)
            if exc_type:
                self.state_tracker.exception_types.add(exc_type)

            # Extract traceback file
            tb_file = self.planner.extract_traceback_file(traceback)
            if tb_file:
                self.state_tracker.add_suspect_file(tb_file, confidence=0.9)

        # Check if tests now pass
        if tests_failed == 0 and tests_passed > 0:
            # Success! Move to expand phase and update learning
            self._transition_phase(PlannerPhase.EXPAND)
            if self.planner_state.last_proposal:
                self.state_tracker.record_hypothesis(
                    proposal_id=self.planner_state.last_proposal.proposal_id,
                    hypothesis=self.planner_state.last_proposal.hypothesis,
                    outcome=HypothesisOutcome.CONFIRMED,
                )
            # Update learning layer with success
            self._update_learning_outcome(success=True, regression=False)
        elif self.planner_state.last_proposal:
            self.state_tracker.record_hypothesis(
                proposal_id=self.planner_state.last_proposal.proposal_id,
                hypothesis=self.planner_state.last_proposal.hypothesis,
                outcome=HypothesisOutcome.FAILED_EFFECT,
            )
            # Update learning layer with failure
            # Calculate partial reward based on test progress
            partial = 0.0
            if tests_passed > 0 and tests_failed > 0:
                partial = tests_passed / (tests_passed + tests_failed) * 0.5
            self._update_learning_outcome(
                success=False,
                regression=feedback.get("regression", False),
                partial_reward=partial,
            )

        # Update reproduction status
        if self.planner_state.phase == PlannerPhase.REPRODUCE and tests_failed > 0:
            self.state_tracker.reproduction_confirmed = True
            if not self.state_tracker.repro_command and self.state_tracker.failing_tests:
                self.state_tracker.repro_command = "pytest " + list(
                    self.state_tracker.failing_tests
                )[0]

    def _update_learning_outcome(
        self,
        success: bool,
        regression: bool = False,
        partial_reward: float | None = None,
    ) -> None:
        """Update learning layer with outcome from verification.
        
        Args:
            success: Whether the patch resolved the issue
            regression: Whether the patch caused a regression
            partial_reward: Partial credit for improvements
        """
        if not self.strategy_selector or not self._last_recommendation:
            return
        try:
            self.strategy_selector.update(
                self._last_recommendation,
                success=success,
                regression=regression,
                partial_reward=partial_reward,
            )
            status = "success" if success else ("regression" if regression else "failure")
            logger.info(
                "Updated learning: %s, strategy=%s, partial=%.2f",
                status,
                self._last_recommendation.strategy,
                partial_reward or 0.0,
            )
        except Exception as e:
            logger.warning("Failed to update learning outcome: %s", e)

    def _transition_phase(self, new_phase: PlannerPhase):
        """Transition to new planning phase."""
        self.planner_state.phase = new_phase
        self.planner_state.phase_attempts = 0

    def _record_proposal(self, proposal: Proposal):
        """Record proposal for history."""
        self.planner_state.last_proposal = proposal

    def select_best_candidate(
        self, candidates: list[Proposal]
    ) -> Proposal:
        """
        Select best proposal from multiple candidates using scoring.

        Args:
            candidates: List of proposal candidates from multi-model generation

        Returns:
            Best proposal
        """
        # Extract narrative from feedback if available
        test_narrative = ""
        if self.last_feedback:
            issue_text = self.last_feedback.get("issue_text", "")
            error_msg = self.last_feedback.get("output", "")
            test_narrative = self._extract_test_narrative(issue_text or error_msg)
        
        scorer = ScoringEngine(
            failing_tests=list(self.state_tracker.failing_tests),
            traceback_frames=self.state_tracker.traceback_frames,
            test_narrative=test_narrative,
        )

        best_proposals = scorer.select_best(candidates, top_n=1)
        return best_proposals[0] if best_proposals else candidates[0]
    
    def _extract_test_narrative(self, issue_text: str) -> str:
        """Extract test narrative from issue or error text.
        
        Looks for patterns like \"Expected: X\", \"Should Y\", \"Test fails with: Z\"
        
        Args:
            issue_text: GitHub issue text or error message
            
        Returns:
            Extracted test narrative or empty string
        """
        if not issue_text:
            return ""
        
        # Patterns to extract test expectations
        patterns = [
            r"Expected:\s*(.+?)(?:\n|$)",
            r"Should\s+(.+?)(?:\.|$)",
            r"Test fails with:\s*(.+?)(?:\n|$)",
            r"Expected\s+behavior:\s*(.+?)(?:\n|$)",
            r"Error:\s*(.+?)(?:\n|$)",
            r"AssertionError:\s*(.+?)(?:\n|$)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, issue_text, re.IGNORECASE | re.MULTILINE)
            if match:
                narrative = match.group(1).strip()
                # Limit length
                if len(narrative) > 200:
                    narrative = narrative[:200] + "..."
                return narrative
        
        # Fallback: take first non-empty line
        lines = [line.strip() for line in issue_text.split('\n') if line.strip()]
        if lines:
            first_line = lines[0]
            if len(first_line) > 200:
                first_line = first_line[:200] + "..."
            return first_line
        
        return ""
