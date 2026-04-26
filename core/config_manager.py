"""
Gestionnaire de configuration pour la classe IA
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .prompt_templates import render_prompt


class ConfigManager:
    """Gère le chargement et l'accès à la configuration (news classifier + usages)."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = Path(__file__).parent.parent
            preferred = base_dir / "config" / "configNewsClassifier.json"
            fallback = base_dir / "config" / "config.json"
            config_path = preferred if preferred.exists() else fallback

        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
        return self._normalize_config(raw)

    def _normalize_config(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Keep config array-native while supporting legacy dict layouts."""
        if isinstance(raw.get("providers"), dict):
            raw["providers"] = self._providers_dict_to_array(raw["providers"])
        if isinstance(raw.get("usages"), dict):
            raw["usages"] = self._usages_dict_to_array(raw["usages"])
        if isinstance(raw.get("classification"), dict):
            raw["usages"] = self._merge_classification_into_usages(
                raw.get("usages", []), raw["classification"]
            )
        return raw

    def _providers_dict_to_array(self, providers: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for name, cfg in providers.items():
            if not isinstance(cfg, dict):
                continue
            services: List[Dict[str, Any]] = []
            if cfg.get("api_completion_url") or cfg.get("model") or cfg.get("api_key"):
                services.append(
                    {
                        "name": "completion",
                        "key": cfg.get("api_key", ""),
                        "url": cfg.get("api_completion_url", ""),
                        "model": cfg.get("model", "gpt-4o"),
                        "maxNbWord": cfg.get("max_nb_word", 4000),
                        "timeout": cfg.get("timeout", {}),
                    }
                )
            if cfg.get("api_embedding_url") or cfg.get("embedding_model"):
                services.append(
                    {
                        "name": "embedding",
                        "key": cfg.get("api_key", ""),
                        "url": cfg.get("api_embedding_url", ""),
                        "model": cfg.get("embedding_model", ""),
                        "timeout": cfg.get("timeout", {}),
                    }
                )
            out.append({"name": name, "services": services})
        return out

    def _usages_dict_to_array(self, usages: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for name, cfg in usages.items():
            if not isinstance(cfg, dict):
                continue
            out.append(
                {
                    "name": name,
                    "template": cfg.get("template"),
                    "prompt": cfg.get("prompt"),
                    "assistantRole": cfg.get("assistantRole") or cfg.get("assistant_role"),
                    "temperature": cfg.get("temperature", 0.3),
                    "provider": cfg.get("provider"),
                    "service": cfg.get("service"),
                }
            )
        return out

    def _merge_classification_into_usages(
        self, usages: Any, classification: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        usage_list = usages if isinstance(usages, list) else []
        by_name = {
            u.get("name"): u
            for u in usage_list
            if isinstance(u, dict) and isinstance(u.get("name"), str)
        }
        if isinstance(classification.get("category"), dict) and "categoryClassification" not in by_name:
            cc = classification["category"]
            usage_list.append(
                {
                    "name": "categoryClassification",
                    "template": cc.get("template"),
                    "prompt": cc.get("prompt"),
                    "assistantRole": cc.get("assistantRole") or cc.get("assistant_role"),
                    "temperature": cc.get("temperature", 0.1),
                    "provider": cc.get("provider"),
                    "service": cc.get("service"),
                }
            )
        if isinstance(classification.get("scenario"), dict) and "scenarioClassification" not in by_name:
            sc = classification["scenario"]
            usage_list.append(
                {
                    "name": "scenarioClassification",
                    "template": sc.get("template"),
                    "prompt": sc.get("prompt"),
                    "assistantRole": sc.get("assistantRole") or sc.get("assistant_role"),
                    "temperature": sc.get("temperature", 0.1),
                    "provider": sc.get("provider"),
                    "service": sc.get("service"),
                }
            )
        return usage_list

    def get_default_provider_type(self) -> str:
        if self.resolve_provider_name("openai"):
            return "openai"
        providers = self.config.get("providers", [])
        if isinstance(providers, list):
            for provider in providers:
                name = provider.get("name") if isinstance(provider, dict) else None
                if isinstance(name, str) and name:
                    return name
        return "openai"

    def resolve_provider_name(self, provider_name: str) -> Optional[str]:
        providers = self.config.get("providers", [])
        if not isinstance(provider_name, str) or not provider_name.strip():
            return None
        wanted = provider_name.strip().lower()
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                name = provider.get("name")
                if isinstance(name, str) and name.strip().lower() == wanted:
                    return name
        return None

    def get_provider_names(self) -> List[str]:
        providers = self.config.get("providers", [])
        if not isinstance(providers, list):
            return []
        names: List[str] = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            name = provider.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names

    def _find_usage(self, usage_name: str) -> Optional[Dict[str, Any]]:
        usages = self.config.get("usages", [])
        if isinstance(usages, list):
            for usage in usages:
                if not isinstance(usage, dict):
                    continue
                if usage.get("name") == usage_name:
                    return usage
            return None
        if isinstance(usages, dict):
            usage = usages.get(usage_name)
            return usage if isinstance(usage, dict) else None
        return None

    def _find_provider(self, provider_name: str) -> Optional[Dict[str, Any]]:
        resolved_name = self.resolve_provider_name(provider_name)
        if not resolved_name:
            return None
        providers = self.config.get("providers", [])
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                if provider.get("name") == resolved_name:
                    return provider
            return None
        if isinstance(providers, dict):
            provider = providers.get(resolved_name)
            if not isinstance(provider, dict):
                return None
            return {"name": resolved_name, "services": self._providers_dict_to_array({resolved_name: provider})[0]["services"]}
        return None

    def get_provider_type(self, provider_name: str) -> str:
        provider = self._find_provider(provider_name)
        if not provider:
            return "openai"
        provider_type = provider.get("type")
        if isinstance(provider_type, str) and provider_type.strip():
            return provider_type.strip().lower()
        return "openai"

    def get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        provider = self._find_provider(provider_name)
        if not provider:
            return {}

        services = provider.get("services", [])
        if not isinstance(services, list):
            return {}

        merged: Dict[str, Any] = {}
        for svc in services:
            if not isinstance(svc, dict):
                continue
            sn = svc.get("name")
            if sn == "completion":
                merged["api_key"] = svc.get("key", "")
                merged["api_completion_url"] = svc.get("url", "")
                merged["model"] = svc.get("model", "gpt-4o")
                merged["max_nb_word"] = svc.get("maxNbWord", svc.get("max_nb_word", 4000))
                merged["timeout"] = svc.get("timeout", {})
            elif sn == "embedding":
                if not merged.get("api_key"):
                    merged["api_key"] = svc.get("key", "")
                merged["api_embedding_url"] = svc.get("url", "")
                merged["embedding_model"] = svc.get("model", "")
                if "timeout" not in merged:
                    merged["timeout"] = svc.get("timeout", {})
        return merged

    def get_usage_config(self, usage_name: str) -> Dict[str, Any]:
        usage = self._find_usage(usage_name)
        if not usage:
            raise ValueError(f"Usage '{usage_name}' not found in configuration")
        return {
            "template": usage.get("template"),
            "prompt": usage.get("prompt"),
            "assistant_role": usage.get("assistantRole") or usage.get("assistant_role"),
            "temperature": usage.get("temperature", 0.3),
            "provider": usage.get("provider"),
            "service": usage.get("service"),
        }

    def get_prompt(self, usage_name: str, **template_vars: Any) -> str:
        usage_config = self.get_usage_config(usage_name)
        if usage_config.get("template"):
            template_name = usage_config["template"]
            return render_prompt(template_name, **template_vars)
        if usage_config.get("prompt"):
            prompt = usage_config["prompt"]
            for key, value in template_vars.items():
                prompt = prompt.replace(f"{{{{{key.upper()}}}}}", str(value))
            return prompt
        raise ValueError(f"No template or prompt found for usage '{usage_name}'")

    def get_classification_config(self, classifier_name: str) -> Dict[str, Any]:
        aliases = {
            "category": ("categoryClassification", "category_classification"),
            "scenario": ("scenarioClassification", "scenario_classification"),
        }
        candidates = aliases.get(classifier_name, (classifier_name,))
        for candidate in candidates:
            usage = self._find_usage(candidate)
            if usage:
                return {
                    "template": usage.get("template"),
                    "prompt": usage.get("prompt"),
                    "assistant_role": usage.get("assistantRole") or usage.get("assistant_role"),
                    "temperature": usage.get("temperature", 0.1),
                    "provider": usage.get("provider"),
                    "service": usage.get("service"),
                }
        raise ValueError(f"Classifier '{classifier_name}' not found in configuration")

    def get_classification_prompt(self, classifier_name: str, **template_vars: Any) -> str:
        classifier_config = self.get_classification_config(classifier_name)
        if classifier_config.get("template"):
            template_name = classifier_config["template"]
            return render_prompt(template_name, **template_vars)
        if classifier_config.get("prompt"):
            prompt = classifier_config["prompt"]
            for key, value in template_vars.items():
                prompt = prompt.replace(f"{{{{{key.upper()}}}}}", str(value))
            return prompt
        raise ValueError(f"No template or prompt found for classifier '{classifier_name}'")

    def reload(self) -> None:
        self.config = self._load_config()
