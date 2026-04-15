"""
LLM Provider System - Support multiple LLM backends

Supported providers:
- OpenAI (ChatGPT)
"""

from .base_provider import BaseLLMProvider
from .openai_provider import OpenAIProvider

__all__ = [
    'BaseLLMProvider',
    'OpenAIProvider',
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
    providers = {
        'openai': OpenAIProvider,
    }
    
    provider_class = providers.get(provider_type.lower())
    if not provider_class:
        raise ValueError(f"Unknown provider type: {provider_type}. Available: {list(providers.keys())}")
    
    return provider_class(config)
