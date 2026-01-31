"""Adaptive Multi-Model Planner.

Dynamically selects LLM models based on problem complexity:
- Fast models (DeepSeek v3) for simple problems
- Standard models (GPT-4o) for moderate problems  
- Reasoning models (o1) for complex problems

Features:
- Complexity estimation before model selection
- Automatic upgrade if initial response is low-confidence
- Cost optimization by using cheaper models when possible
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .complexity import ComplexityEstimator, ComplexityLevel

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in a repair plan."""
    
    title: str
    description: str
    action_type: str  # "edit", "add", "delete", "test", "verify"
    target_file: str | None = None
    details: dict = field(default_factory=dict)


@dataclass
class Plan:
    """A complete repair plan."""
    
    goal: str
    steps: list[PlanStep]
    estimated_complexity: ComplexityLevel
    model_used: str
    confidence: float
    reasoning: str


class AdaptivePlanner:
    """Planner with adaptive model selection.
    
    Model Hierarchy:
    - FAST: deepseek-v3, gpt-4o-mini (for TRIVIAL/SIMPLE)
    - STANDARD: gpt-4o, claude-3.5-sonnet (for MODERATE)
    - REASONING: o1-mini, o1 (for COMPLEX/VERY_COMPLEX)
    
    Usage:
        planner = AdaptivePlanner(llm_client, memory_adapter)
        plan = await planner.create_plan(goal, context)
    """
    
    # Model tiers
    FAST_MODELS = ["deepseek-v3", "gpt-4o-mini"]
    STANDARD_MODELS = ["gpt-4o", "claude-3.5-sonnet"]
    REASONING_MODELS = ["o1-mini", "o1"]
    
    # Default model for each tier
    DEFAULT_FAST = "deepseek-v3"
    DEFAULT_STANDARD = "gpt-4o"
    DEFAULT_REASONING = "o1-mini"
    
    def __init__(
        self,
        llm_client: Any = None,
        memory_adapter: Any = None,
        enable_upgrade: bool = True,
        confidence_threshold: float = 0.6,
    ):
        """Initialize planner.
        
        Args:
            llm_client: Enhanced LLM client for API calls
            memory_adapter: Memory adapter for historical queries
            enable_upgrade: Whether to upgrade models on low confidence
            confidence_threshold: Threshold below which to upgrade model
        """
        self.llm_client = llm_client
        self.memory = memory_adapter
        self.enable_upgrade = enable_upgrade
        self.confidence_threshold = confidence_threshold
        self.complexity_estimator = ComplexityEstimator(memory_adapter)
        
        # Lazy import LLM client if not provided
        if self.llm_client is None:
            self._init_llm_client()
    
    def _init_llm_client(self):
        """Initialize LLM client lazily."""
        try:
            from ..llm.enhanced_client import get_llm_client
            self.llm_client = get_llm_client()
        except ImportError:
            logger.warning("Enhanced LLM client not available")
    
    async def create_plan(
        self,
        goal: str,
        context: dict,
        force_model: str | None = None,
    ) -> Plan:
        """Create a repair plan for the given goal.
        
        Args:
            goal: Natural language repair goal
            context: Context dict with codebase info
            force_model: Force use of specific model (bypasses adaptive selection)
        
        Returns:
            Plan with steps and metadata
        """
        # Step 1: Estimate complexity
        complexity = self.complexity_estimator.estimate(goal, context)
        
        logger.info(
            "plan_complexity_estimated",
            extra={
                "goal": goal[:100],
                "level": complexity.level.name,
                "recommended_tier": complexity.recommended_model_tier,
            },
        )
        
        # Step 2: Select model
        if force_model:
            model = force_model
        else:
            model = self._select_model(complexity.recommended_model_tier)
        
        # Step 3: Generate plan
        plan = await self._generate_plan(goal, context, model, complexity)
        
        # Step 4: Upgrade if low confidence and enabled
        if self.enable_upgrade and plan.confidence < self.confidence_threshold:
            upgraded_model = self._get_upgrade_model(model)
            if upgraded_model:
                logger.info(
                    "upgrading_model",
                    extra={
                        "from": model,
                        "to": upgraded_model,
                        "confidence": plan.confidence,
                    },
                )
                plan = await self._generate_plan(goal, context, upgraded_model, complexity)
        
        return plan
    
    def _select_model(self, tier: str) -> str:
        """Select a model for the given tier."""
        if tier == "fast":
            return self.DEFAULT_FAST
        elif tier == "standard":
            return self.DEFAULT_STANDARD
        elif tier == "reasoning":
            return self.DEFAULT_REASONING
        else:
            return self.DEFAULT_STANDARD
    
    def _get_upgrade_model(self, current_model: str) -> str | None:
        """Get the next tier model for upgrade."""
        if current_model in self.FAST_MODELS:
            return self.DEFAULT_STANDARD
        elif current_model in self.STANDARD_MODELS:
            return self.DEFAULT_REASONING
        else:
            return None  # Already at highest tier
    
    async def _generate_plan(
        self,
        goal: str,
        context: dict,
        model: str,
        complexity: Any,
    ) -> Plan:
        """Generate a plan using the specified model."""
        prompt = self._build_planning_prompt(goal, context)
        system_prompt = self._get_system_prompt()
        
        try:
            # Call LLM
            if self.llm_client:
                response = await self.llm_client.call(
                    model_key=model,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                plan_text = response.content
            else:
                # Fallback for testing
                plan_text = f"[Mock plan for: {goal}]"
            
            # Parse response into plan
            steps = self._parse_plan_response(plan_text)
            confidence = self._estimate_confidence(steps, context)
            
            return Plan(
                goal=goal,
                steps=steps,
                estimated_complexity=complexity.level,
                model_used=model,
                confidence=confidence,
                reasoning=complexity.reasoning,
            )
            
        except Exception as e:
            logger.error("plan_generation_failed", error=str(e))
            # Return minimal fallback plan
            return Plan(
                goal=goal,
                steps=[PlanStep(
                    title="Manual investigation required",
                    description=f"Automated planning failed: {e}",
                    action_type="verify",
                )],
                estimated_complexity=complexity.level,
                model_used=model,
                confidence=0.0,
                reasoning=f"Error: {e}",
            )
    
    def _build_planning_prompt(self, goal: str, context: dict) -> str:
        """Build the planning prompt."""
        parts = [
            f"# Repair Goal\n{goal}",
            "",
            "# Context",
        ]
        
        if context.get("failing_tests"):
            tests = context["failing_tests"][:5]  # Limit for prompt size
            parts.append(f"Failing tests: {', '.join(tests)}")
        
        if context.get("error_type"):
            parts.append(f"Error type: {context['error_type']}")
        
        if context.get("error_message"):
            parts.append(f"Error: {context['error_message'][:500]}")
        
        if context.get("touched_files"):
            files = context["touched_files"][:10]
            parts.append(f"Likely files: {', '.join(files)}")
        
        parts.extend([
            "",
            "# Instructions",
            "Create a step-by-step plan to fix this issue.",
            "Each step should be one of: edit, add, delete, test, verify",
            "Be specific about which files to modify and what changes to make.",
            "",
            "Format your response as a numbered list:",
            "1. [action_type] file.py: description",
            "2. [action_type] file.py: description",
            "...",
        ])
        
        return "\n".join(parts)
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for planning."""
        return """You are an expert software engineer tasked with creating repair plans.

Your plans should be:
1. Specific - Name exact files and describe exact changes
2. Minimal - Only include necessary changes
3. Safe - Avoid breaking existing functionality
4. Testable - Include verification steps

Focus on the root cause, not just symptoms."""
    
    def _parse_plan_response(self, response: str) -> list[PlanStep]:
        """Parse LLM response into plan steps."""
        steps = []
        lines = response.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip non-step lines
            if not (line[0].isdigit() or line.startswith("-")):
                continue
            
            # Remove leading number/bullet
            step_text = line.lstrip("0123456789.-) ")
            
            # Try to extract action type
            action_type = "edit"
            for action in ["edit", "add", "delete", "test", "verify"]:
                if step_text.lower().startswith(f"[{action}]"):
                    action_type = action
                    step_text = step_text[len(action)+2:].strip()
                    break
            
            # Extract file if present
            target_file = None
            if ":" in step_text:
                parts = step_text.split(":", 1)
                potential_file = parts[0].strip()
                if "." in potential_file or "/" in potential_file:
                    target_file = potential_file
                    step_text = parts[1].strip() if len(parts) > 1 else ""
            
            steps.append(PlanStep(
                title=step_text[:100] if step_text else "Untitled step",
                description=step_text,
                action_type=action_type,
                target_file=target_file,
            ))
        
        return steps if steps else [PlanStep(
            title="No steps parsed",
            description="Could not parse plan from response",
            action_type="verify",
        )]
    
    def _estimate_confidence(self, steps: list[PlanStep], context: dict) -> float:
        """Estimate confidence in the generated plan."""
        confidence = 0.5  # Base
        
        # More steps = more complex = less confident
        if len(steps) > 10:
            confidence -= 0.2
        elif len(steps) < 3:
            confidence += 0.1
        
        # Steps with specific files = more confident
        specific_steps = sum(1 for s in steps if s.target_file)
        if specific_steps > 0:
            confidence += 0.1 * min(specific_steps, 3)
        
        # Has verification steps = more confident
        has_verify = any(s.action_type == "verify" for s in steps)
        if has_verify:
            confidence += 0.1
        
        return max(0.0, min(1.0, confidence))
