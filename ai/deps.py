"""Shared dependencies (IA instance)."""

from pathlib import Path
from typing import Dict, Optional

import logging

from core.config_manager import ConfigManager
from core.ia import IA

_base_dir = Path(__file__).resolve().parent.parent
_config = _base_dir / "config" / "configNewsClassifier.json"
_config_path = str(_config if _config.exists() else _base_dir / "config" / "config.json")
_config_manager = ConfigManager(config_path=_config_path)
_ia_by_provider: Dict[str, IA] = {}
_provider_errors: Dict[str, str] = {}

logger = logging.getLogger(__name__)


class ProviderUnavailableError(Exception):
    """Raised when the requested provider is unknown or unavailable."""


def _initialize_all_providers() -> None:
    for provider_name in _config_manager.get_provider_names():
        cache_key = provider_name.lower()
        try:
            _ia_by_provider[cache_key] = IA(
                config_path=_config_path,
                provider_type=provider_name,
                allow_fallback=False,
            )
            logger.info("Provider initialized: %s", provider_name)
        except Exception as exc:
            _provider_errors[cache_key] = str(exc)
            logger.warning("Provider failed to initialize: %s (%s)", provider_name, exc)


_initialize_all_providers()


def get_ia(provider: Optional[str] = None) -> IA:
    requested = (provider or "openai").strip()
    resolved = _config_manager.resolve_provider_name(requested)
    if not resolved:
        raise ProviderUnavailableError(f"Provider '{requested}' was not found.")

    cache_key = resolved.lower()
    ia = _ia_by_provider.get(cache_key)
    if ia is None:
        detail = _provider_errors.get(cache_key, "not available")
        raise ProviderUnavailableError(f"Provider '{resolved}' is not available: {detail}")

    return ia
