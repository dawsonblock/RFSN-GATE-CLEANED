"""Enhanced LLM client with latest models (2026).

Provides a unified async interface for multiple LLM providers:
- DeepSeek v3 (fast, cost-effective)
- OpenAI o1 / o1-mini (deep reasoning)
- OpenAI GPT-4o (standard)
- Claude 3.7 Sonnet (balanced)
- Gemini 2.0 Flash (fast, multimodal)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

ModelProvider = Literal["openai", "anthropic", "google", "deepseek"]


@dataclass
class ModelConfig:
    """Configuration for LLM models."""
    
    provider: ModelProvider
    model_name: str
    max_tokens: int = 8192
    temperature: float = 0.0
    reasoning_effort: str | None = None  # For o1 models: "low", "medium", "high"
    supports_system_prompt: bool = True
    cost_per_1k_input: float = 0.0  # For cost tracking
    cost_per_1k_output: float = 0.0


# Latest models (January 2026)
LATEST_MODELS: dict[str, ModelConfig] = {
    # DeepSeek models - excellent cost/performance ratio
    "deepseek-v3": ModelConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        max_tokens=8192,
        cost_per_1k_input=0.00014,
        cost_per_1k_output=0.00028,
    ),
    "deepseek-coder": ModelConfig(
        provider="deepseek",
        model_name="deepseek-coder",
        max_tokens=16384,
        cost_per_1k_input=0.00014,
        cost_per_1k_output=0.00028,
    ),
    
    # OpenAI reasoning models
    "o1": ModelConfig(
        provider="openai",
        model_name="o1",
        max_tokens=32768,
        reasoning_effort="high",
        supports_system_prompt=False,  # o1 doesn't support system prompts
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.060,
    ),
    "o1-mini": ModelConfig(
        provider="openai",
        model_name="o1-mini",
        max_tokens=16384,
        reasoning_effort="medium",
        supports_system_prompt=False,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.012,
    ),
    
    # OpenAI standard models
    "gpt-4o": ModelConfig(
        provider="openai",
        model_name="gpt-4o-2024-11-20",
        max_tokens=16384,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.010,
    ),
    "gpt-4o-mini": ModelConfig(
        provider="openai",
        model_name="gpt-4o-mini",
        max_tokens=16384,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
    ),
    
    # Anthropic models
    "claude-3.7-sonnet": ModelConfig(
        provider="anthropic",
        model_name="claude-3-7-sonnet-20250219",
        max_tokens=8192,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
    ),
    "claude-3.5-sonnet": ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        max_tokens=8192,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
    ),
    
    # Google models
    "gemini-2.0-flash": ModelConfig(
        provider="google",
        model_name="gemini-2.0-flash-exp",
        max_tokens=8192,
        cost_per_1k_input=0.00035,
        cost_per_1k_output=0.0014,
    ),
    "gemini-1.5-pro": ModelConfig(
        provider="google",
        model_name="gemini-1.5-pro-latest",
        max_tokens=8192,
        cost_per_1k_input=0.00125,
        cost_per_1k_output=0.005,
    ),
}


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class EnhancedLLMClient:
    """Unified async client for all LLM providers.
    
    Usage:
        client = EnhancedLLMClient()
        
        # Single call
        response = await client.call(
            model_key="deepseek-v3",
            prompt="Write a function to...",
            system_prompt="You are a coding assistant."
        )
        
        # Batch calls
        responses = await client.call_batch([
            {"model_key": "deepseek-v3", "prompt": "..."},
            {"model_key": "gpt-4o", "prompt": "..."},
        ])
    """
    
    def __init__(self):
        self._openai_client = None
        self._anthropic_client = None
        self._deepseek_client = None
        self._google_configured = False
        self._init_clients()
    
    def _init_clients(self):
        """Initialize API clients lazily."""
        # OpenAI
        if api_key := os.getenv("OPENAI_API_KEY"):
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(api_key=api_key)
                logger.debug("OpenAI client initialized")
            except ImportError:
                logger.warning("openai package not installed")
        
        # Anthropic
        if api_key := os.getenv("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self._anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
                logger.debug("Anthropic client initialized")
            except ImportError:
                logger.warning("anthropic package not installed")
        
        # DeepSeek (uses OpenAI-compatible API)
        if api_key := os.getenv("DEEPSEEK_API_KEY"):
            try:
                from openai import AsyncOpenAI
                self._deepseek_client = AsyncOpenAI(
                    api_key=api_key,
                    base_url="https://api.deepseek.com"
                )
                logger.debug("DeepSeek client initialized")
            except ImportError:
                logger.warning("openai package not installed (needed for DeepSeek)")
        
        # Google
        if api_key := os.getenv("GOOGLE_API_KEY"):
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._google_configured = True
                logger.debug("Google Gemini configured")
            except ImportError:
                logger.warning("google-generativeai package not installed")
    
    def available_models(self) -> list[str]:
        """Return list of available models based on configured API keys."""
        available = []
        
        if self._openai_client:
            available.extend(["o1", "o1-mini", "gpt-4o", "gpt-4o-mini"])
        if self._anthropic_client:
            available.extend(["claude-3.7-sonnet", "claude-3.5-sonnet"])
        if self._deepseek_client:
            available.extend(["deepseek-v3", "deepseek-coder"])
        if self._google_configured:
            available.extend(["gemini-2.0-flash", "gemini-1.5-pro"])
        
        return available
    
    async def call(
        self,
        model_key: str,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Call any supported model with unified interface.
        
        Args:
            model_key: Model identifier (e.g., "deepseek-v3", "o1-mini")
            prompt: User prompt
            system_prompt: System prompt (ignored for o1 models)
            **kwargs: Override model config (max_tokens, temperature, etc.)
        
        Returns:
            LLMResponse with content and usage stats
        """
        import time
        
        config = LATEST_MODELS.get(model_key)
        if not config:
            raise ValueError(f"Unknown model: {model_key}. Available: {list(LATEST_MODELS.keys())}")
        
        start_time = time.time()
        
        if config.provider == "openai":
            response = await self._call_openai(config, prompt, system_prompt, **kwargs)
        elif config.provider == "anthropic":
            response = await self._call_anthropic(config, prompt, system_prompt, **kwargs)
        elif config.provider == "deepseek":
            response = await self._call_deepseek(config, prompt, system_prompt, **kwargs)
        elif config.provider == "google":
            response = await self._call_google(config, prompt, system_prompt, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {config.provider}")
        
        response.latency_ms = (time.time() - start_time) * 1000
        response.cost_usd = self._calculate_cost(config, response)
        
        logger.info(
            "LLM call completed",
            extra={
                "model": model_key,
                "tokens": response.total_tokens,
                "latency_ms": response.latency_ms,
                "cost_usd": response.cost_usd,
            },
        )
        
        return response
    
    async def _call_openai(
        self,
        config: ModelConfig,
        prompt: str,
        system_prompt: str | None,
        **kwargs,
    ) -> LLMResponse:
        """Call OpenAI models (GPT-4o, o1)."""
        if not self._openai_client:
            raise RuntimeError("OpenAI client not configured. Set OPENAI_API_KEY.")
        
        messages = []
        
        # o1 models don't support system messages
        if system_prompt and config.supports_system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        elif system_prompt and not config.supports_system_prompt:
            # Prepend system prompt to user message for o1
            prompt = f"{system_prompt}\n\n---\n\n{prompt}"
        
        messages.append({"role": "user", "content": prompt})
        
        call_kwargs = {
            "model": config.model_name,
            "messages": messages,
            "max_completion_tokens": kwargs.get("max_tokens", config.max_tokens),
        }
        
        # Only set temperature for non-o1 models
        if config.supports_system_prompt:
            call_kwargs["temperature"] = kwargs.get("temperature", config.temperature)
        
        # Add reasoning_effort for o1 models
        if config.reasoning_effort:
            call_kwargs["reasoning_effort"] = kwargs.get("reasoning_effort", config.reasoning_effort)
        
        response = await self._openai_client.chat.completions.create(**call_kwargs)
        
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=config.model_name,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )
    
    async def _call_deepseek(
        self,
        config: ModelConfig,
        prompt: str,
        system_prompt: str | None,
        **kwargs,
    ) -> LLMResponse:
        """Call DeepSeek models."""
        if not self._deepseek_client:
            raise RuntimeError("DeepSeek client not configured. Set DEEPSEEK_API_KEY.")
        
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = await self._deepseek_client.chat.completions.create(
            model=config.model_name,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", config.max_tokens),
            temperature=kwargs.get("temperature", config.temperature),
        )
        
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=config.model_name,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )
    
    async def _call_anthropic(
        self,
        config: ModelConfig,
        prompt: str,
        system_prompt: str | None,
        **kwargs,
    ) -> LLMResponse:
        """Call Claude models."""
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client not configured. Set ANTHROPIC_API_KEY.")
        
        response = await self._anthropic_client.messages.create(
            model=config.model_name,
            max_tokens=kwargs.get("max_tokens", config.max_tokens),
            temperature=kwargs.get("temperature", config.temperature),
            system=system_prompt or "",
            messages=[{"role": "user", "content": prompt}],
        )
        
        return LLMResponse(
            content=response.content[0].text if response.content else "",
            model=config.model_name,
            prompt_tokens=response.usage.input_tokens if response.usage else 0,
            completion_tokens=response.usage.output_tokens if response.usage else 0,
            total_tokens=(response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0,
        )
    
    async def _call_google(
        self,
        config: ModelConfig,
        prompt: str,
        system_prompt: str | None,
        **kwargs,
    ) -> LLMResponse:
        """Call Gemini models."""
        if not self._google_configured:
            raise RuntimeError("Google Gemini not configured. Set GOOGLE_API_KEY.")
        
        import google.generativeai as genai
        
        model = genai.GenerativeModel(
            model_name=config.model_name,
            system_instruction=system_prompt,
        )
        
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=kwargs.get("max_tokens", config.max_tokens),
            temperature=kwargs.get("temperature", config.temperature),
        )
        
        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config,
        )
        
        # Gemini doesn't expose token counts easily in async
        return LLMResponse(
            content=response.text if response.text else "",
            model=config.model_name,
            prompt_tokens=0,  # Not available in async API
            completion_tokens=0,
            total_tokens=0,
        )
    
    def _calculate_cost(self, config: ModelConfig, response: LLMResponse) -> float:
        """Calculate cost in USD based on token usage."""
        input_cost = (response.prompt_tokens / 1000) * config.cost_per_1k_input
        output_cost = (response.completion_tokens / 1000) * config.cost_per_1k_output
        return round(input_cost + output_cost, 6)
    
    async def call_batch(
        self,
        requests: list[dict],
        max_concurrent: int = 5,
    ) -> list[LLMResponse]:
        """Call multiple models in parallel.
        
        Args:
            requests: List of dicts with model_key, prompt, system_prompt
            max_concurrent: Maximum concurrent requests
        
        Returns:
            List of LLMResponse objects
        """
        import asyncio
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def limited_call(req: dict) -> LLMResponse:
            async with semaphore:
                return await self.call(**req)
        
        return await asyncio.gather(*[limited_call(r) for r in requests])


# Singleton instance
_client: EnhancedLLMClient | None = None


def get_llm_client() -> EnhancedLLMClient:
    """Get or create LLM client singleton."""
    global _client
    if _client is None:
        _client = EnhancedLLMClient()
    return _client
