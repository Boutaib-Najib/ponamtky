"""Shared dependencies (IA instance)."""

from pathlib import Path

from core.ia import IA

_base_dir = Path(__file__).resolve().parent.parent
_config = _base_dir / "config" / "configNewsClassifier.json"
_ia = IA(
    config_path=str(_config if _config.exists() else _base_dir / "config" / "config.json")
)


def get_ia() -> IA:
    return _ia
