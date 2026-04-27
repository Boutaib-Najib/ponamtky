import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def extract_api_key(headers) -> str:
    """
    Extract API key from request headers.
    Header:
    - X-AUTH-API-KEY: <token>
    """
    return (headers.get("X-AUTH-API-KEY") or headers.get("x-auth-api-key") or "").strip()


def _read_keys_file(path: Path) -> Set[str]:
    """
    Read newline-delimited API keys from a text file.
    Ignores empty lines and lines starting with '#'.
    """
    keys: Set[str] = set()
    raw = path.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        keys.add(s)
    return keys


@dataclass
class ApiKeyStore:
    path: Optional[Path]
    refresh_seconds: int = 300
    enabled: bool = True

    _keys: Set[str] = None  # type: ignore[assignment]
    _last_load_ts: float = 0.0
    _last_mtime: float = 0.0

    def __post_init__(self) -> None:
        self._keys = set()

    @classmethod
    def from_env(cls) -> "ApiKeyStore":
        enabled = _env_bool("AI_AUTH_ENABLED", True)
        path_raw = os.environ.get("AI_AUTH_KEYS_FILE", "").strip()
        path = Path(path_raw) if path_raw else None
        refresh = int(os.environ.get("AI_AUTH_REFRESH_SECONDS", "300").strip() or "300")
        return cls(path=path, refresh_seconds=refresh, enabled=enabled)

    def _should_reload(self) -> bool:
        if not self.path:
            return False
        now = time.time()
        if now - self._last_load_ts >= self.refresh_seconds:
            return True
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        return mtime > self._last_mtime

    def reload_if_needed(self) -> None:
        if not self.enabled:
            return
        if not self.path:
            return
        if not self._should_reload():
            return
        try:
            keys = _read_keys_file(self.path)
            self._keys = keys
            self._last_load_ts = time.time()
            self._last_mtime = self.path.stat().st_mtime
            logger.info("Auth keys loaded: %s keys from %s", len(keys), str(self.path))
        except Exception as exc:
            # Keep last known keys if reload fails.
            logger.warning("Auth keys reload failed (%s): %s", str(self.path), exc)
            self._last_load_ts = time.time()

    def is_allowed(self, token: str) -> bool:
        if not self.enabled:
            return True
        self.reload_if_needed()
        if not self.path:
            return False
        if not token:
            return False
        return token in self._keys


_store = ApiKeyStore.from_env()


def get_key_store() -> ApiKeyStore:
    return _store

