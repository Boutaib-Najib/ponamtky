"""
LLM Provider System - Support multiple LLM backends

Supported providers:
- OpenAI-compatible APIs
"""

from .base_provider import BaseLLMProvider
from .openai_provider import OpenAICompatibleProvider

__all__ = [
    'BaseLLMProvider',
    'OpenAICompatibleProvider',
    'get_provider'
]


def get_provider(provider_type: str, config: dict) -> BaseLLMProvider:
    """
    Factory function to get appropriate LLM provider
    
    Args:
        provider_type: Type of provider ('openai')
        config: Configuration dictionary for the provider
        
    Returns:
        Instance of appropriate provider
    """
    normalized = provider_type.lower()
    providers = {
        'openai': OpenAICompatibleProvider,
        'openai_compatible': OpenAICompatibleProvider,
        'openai-compatible': OpenAICompatibleProvider,
    }

    provider_class = providers.get(normalized)
    if not provider_class:
        raise ValueError(f"Unknown provider type: {provider_type}. Available: {list(providers.keys())}")
    
    return provider_class(config)
