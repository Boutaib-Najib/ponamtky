"""
Base LLM Provider - Abstract interface for all LLM providers
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers
    All providers must implement these methods
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize provider with configuration
        
        Args:
            config: Provider-specific configuration
        """
        self.config = config
        self.provider_name = self.__class__.__name__
    
    @abstractmethod
    def complete(
        self, 
        prompt: str, 
        system_message: str = "", 
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """
        Generate a completion for the given prompt
        
        Args:
            prompt: User prompt
            system_message: System message/behavior
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text or None on error
        """
        pass
    
    @abstractmethod
    def embed(self, text: str) -> Optional[List[float]]:
        """
        Generate embeddings for the given text
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding or None on error
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is available and properly configured
        
        Returns:
            True if provider can be used, False otherwise
        """
        pass
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the model being used
        
        Returns:
            Dictionary with model information
        """
        return {
            "provider": self.provider_name,
            "model": self.config.get("model", "unknown"),
            "config": self.config
        }
    
    def supports_embeddings(self) -> bool:
        """
        Check if provider supports embeddings
        
        Returns:
            True if embeddings are supported
        """
        return True
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate cost for the given token counts
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Estimated cost in USD (0.0 for local models)
        """
        return 0.0
