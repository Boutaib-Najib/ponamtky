"""
OpenAI-compatible Provider implementation.
"""

import logging
import os
from typing import Optional, List, Dict, Any

import requests

from .base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Provider for OpenAI-compatible chat/embedding APIs."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = self._resolve_api_key(config.get("api_key", ""))
        self.api_url = config.get("api_completion_url", "")
        self.embedding_url = config.get("api_embedding_url", "")
        self.model = config.get("model", "")
        self.embedding_model = config.get("embedding_model", "")
        self.timeout = config.get("timeout", {"connect": 10, "read": 30})
    
    @staticmethod
    def _resolve_api_key(key: str) -> str:
        """Resolve API key: if it starts with 'ENV:' read from environment variable."""
        if key and key.startswith("ENV:"):
            env_var = key[4:]
            resolved = os.environ.get(env_var, "")
            if not resolved:
                logger.warning(f"Environment variable {env_var} is not set")
            return resolved
        return key
    
    def complete(
        self, 
        prompt: str, 
        system_message: str = "", 
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """Generate completion using an OpenAI-compatible API."""
        try:
            request_body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature
            }
            
            if max_tokens:
                request_body["max_tokens"] = max_tokens
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            timeout = (
                self.timeout.get("connect", 10),
                self.timeout.get("read", 30)
            )
            
            response = requests.post(
                self.api_url,
                json=request_body,
                headers=headers,
                timeout=timeout
            )
            
            if response.status_code == 200:
                response_json = response.json()
                return response_json["choices"][0]["message"]["content"]
            else:
                logger.error(f"OpenAI-compatible API error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("OpenAI-compatible request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenAI-compatible network error: {e}")
            return None
        except Exception as e:
            logger.error(f"OpenAI-compatible unexpected error: {e}")
            return None
    
    def embed(self, text: str) -> Optional[List[float]]:
        """Generate embeddings using an OpenAI-compatible API."""
        try:
            request_body = {
                "model": self.embedding_model,
                "input": text
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            timeout = (
                self.timeout.get("connect", 10),
                self.timeout.get("read", 30)
            )
            
            response = requests.post(
                self.embedding_url,
                json=request_body,
                headers=headers,
                timeout=timeout
            )
            
            if response.status_code == 200:
                response_json = response.json()
                return response_json["data"][0]["embedding"]
            else:
                logger.error(f"OpenAI-compatible embedding error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"OpenAI-compatible embedding error: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if provider is properly configured."""
        return bool(self.api_key and self.api_url and self.model)
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for OpenAI-style pricing."""
        # GPT-4o pricing (as of 2024)
        cost_per_1k_input = 0.005  # $5 per 1M tokens
        cost_per_1k_output = 0.015  # $15 per 1M tokens
        
        input_cost = (input_tokens / 1000) * cost_per_1k_input
        output_cost = (output_tokens / 1000) * cost_per_1k_output
        
        return input_cost + output_cost
