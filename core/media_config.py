"""
Configuration des médias pour le web scraping authentifié.
Équivalent Python des classes Java Media + MediaConfig.

Chaque entrée Media décrit un domaine nécessitant un traitement spécifique :
  - login (identifiants + sélecteurs CSS du formulaire)
  - cookie consent (sélecteur du bouton d'acceptation)
  - résolution de captcha (via CapSolver API)
  - mode d'extraction du texte (reader vs normal)

La configuration est chargée depuis la section "media" du fichier config.json.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Media:
    """
    Properties required to crawl a URL for a specific media/domain.
    Mirrors the Java Media class field-by-field.
    
    Example JSON entry::
    
        {
            "name": "ft.com",
            "needLogin": true,
            "userName": "user@example.com",
            "pwd": "secret",
            "loginUrl": "https://accounts.ft.com/login",
            "userNameField": "#enter-email",
            "pwdField": "#enter-password",
            "cookie": null,
            "needCaptcha": true,
            "websiteKey": "ab5cba1f-...",
            "needTextNormal": false
        }
    """
    # Domain name (e.g. "ft.com", "law360.com")
    name: str = ""
    # Whether this media requires login before scraping
    need_login: bool = False
    # Username for login
    user_name: str = ""
    # Password for login
    pwd: str = ""
    # URL of the login page
    login_url: str = ""
    # CSS selector for the username input field
    user_name_field: str = ""
    # CSS selector for the password input field
    pwd_field: str = ""
    # CSS selector for the cookie-consent / accept button (clicked before login)
    cookie: Optional[str] = None
    # Whether the site uses CAPTCHA (hCaptcha) on the login page
    need_captcha: bool = False
    # hCaptcha website key (required when need_captcha is True)
    website_key: str = ""
    # If True, use normal-mode extraction instead of reader-mode
    need_text_normal: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Media":
        """Create a Media instance from a JSON-like dictionary (camelCase keys)."""
        return cls(
            name=data.get("name", ""),
            need_login=data.get("needLogin", False),
            user_name=data.get("userName", ""),
            pwd=data.get("pwd", ""),
            login_url=data.get("loginUrl", ""),
            user_name_field=data.get("userNameField", ""),
            pwd_field=data.get("pwdField", ""),
            cookie=data.get("cookie"),
            need_captcha=data.get("needCaptcha", False),
            website_key=data.get("websiteKey", ""),
            need_text_normal=data.get("needTextNormal", False),
        )

    def to_dict(self) -> dict:
        """Serialize back to camelCase dict for JSON export."""
        return {
            "name": self.name,
            "needLogin": self.need_login,
            "userName": self.user_name,
            "pwd": self.pwd,
            "loginUrl": self.login_url,
            "userNameField": self.user_name_field,
            "pwdField": self.pwd_field,
            "cookie": self.cookie,
            "needCaptcha": self.need_captcha,
            "websiteKey": self.website_key,
            "needTextNormal": self.need_text_normal,
        }


@dataclass
class MediaConfig:
    """
    Manages domain exclusions and domain-specific scraping configurations.
    Mirrors the Java MediaConfig class.
    
    Loaded from the ``"media"`` section of config.json::
    
        "media": {
            "exclusions": ["twitter.com", "facebook.com"],
            "specificMedia": [ { ... Media entries ... } ],
            "capsolver_api_key": "CAP-..."
        }
    """
    # Domains excluded from automated extraction
    exclusions: Set[str] = field(default_factory=set)
    # Per-domain scraping config (login, captcha, etc.)
    specific_media: List[Media] = field(default_factory=list)
    # CapSolver API key for hCaptcha resolution
    capsolver_api_key: str = ""
    # Domain-specific text cleaning rules
    cleaning_rules: Dict[str, List[dict]] = field(default_factory=dict)

    # Internal lookup map (lazy-initialized)
    _media_map: Dict[str, Media] = field(default_factory=dict, repr=False, init=False)

    def __post_init__(self):
        self._populate_map()

    def _populate_map(self):
        """Build the domain → Media lookup table."""
        self._media_map = {}
        for media in self.specific_media:
            if media.name:
                self._media_map[media.name] = media

    # ---------- Public API (mirrors Java MediaConfig) ----------

    def is_excluded(self, domain: str) -> bool:
        """Check if a domain is in the exclusion set."""
        if not domain:
            return False
        return domain in self.exclusions

    def is_specific(self, domain: str) -> bool:
        """Check if a domain has specific scraping config."""
        if not domain:
            return False
        return domain in self._media_map

    def get_specific(self, domain: str) -> Optional[Media]:
        """Return the Media config for a given domain, or None."""
        return self._media_map.get(domain)

    def get_cleaning_rules(self, domain: str) -> Optional[List[dict]]:
        """Return domain-specific text cleaning rules, or None."""
        if not domain:
            return None
        domain = domain.lower()
        # Exact match
        if domain in self.cleaning_rules:
            return self.cleaning_rules[domain]
        # Suffix match (e.g. 'ft.com' matches 'www.ft.com')
        for rule_domain, rules in self.cleaning_rules.items():
            if domain == rule_domain or domain.endswith('.' + rule_domain):
                return rules
        return None

    # ---------- Factory ----------

    @classmethod
    def from_dict(cls, data: dict) -> "MediaConfig":
        """Create a MediaConfig from the ``"media"`` section of config.json."""
        exclusions = set(data.get("exclusions", []))
        specific_media = [
            Media.from_dict(m) for m in data.get("specificMedia", [])
        ]
        capsolver_api_key = data.get("capsolverApiKey", "")
        cleaning_rules = data.get("cleaningRules", {})
        return cls(
            exclusions=exclusions,
            specific_media=specific_media,
            capsolver_api_key=capsolver_api_key,
            cleaning_rules=cleaning_rules,
        )

    @classmethod
    def from_config_file(cls, config_path: Optional[str] = None) -> "MediaConfig":
        """
        Load MediaConfig from configScraper.json (preferred) or legacy config.json.

        Args:
            config_path: Path to a JSON file containing a ``media`` object (SOW), or
                legacy root config with ``media`` section.

        Returns:
            MediaConfig instance (empty if section is missing).
        """
        if config_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            preferred = base_dir / "config" / "configScraper.json"
            fallback = base_dir / "config" / "config.json"
            config_path = str(preferred if preferred.exists() else fallback)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            media_section = config.get("media", {})
            if not media_section:
                logger.info("No 'media' section — using empty MediaConfig")
                return cls()
            return cls.from_dict(media_section)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_path}")
            return cls()
        except Exception as e:
            logger.error(f"Failed to load MediaConfig from {config_path}: {e}")
            return cls()

    @classmethod
    def empty(cls) -> "MediaConfig":
        """Return an empty (no-op) MediaConfig."""
        return cls()
