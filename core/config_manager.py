"""
Gestionnaire de configuration pour la classe IA
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

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
        """Support array-shaped providers/usages (SOW) and legacy dict layout."""
        if isinstance(raw.get("providers"), list):
            raw = self._normalize_providers_usages_array(raw)
        elif isinstance(raw.get("usages"), list):
            raw = self._normalize_usages_array_only(raw)
        return raw

    def _normalize_providers_usages_array(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        providers_dict: Dict[str, Any] = {}
        for p in raw.get("providers", []):
            name = p.get("name")
            if not name:
                continue
            merged: Dict[str, Any] = {}
            for svc in p.get("services", []):
                sn = svc.get("name")
                if sn == "completion":
                    merged["api_key"] = svc.get("key", "")
                    merged["api_completion_url"] = svc.get("url", "")
                    merged["model"] = svc.get("model", "gpt-4o")
                    merged["max_nb_word"] = svc.get(
                        "maxNbWord", svc.get("max_nb_word", 4000)
                    )
                    merged["timeout"] = svc.get("timeout", {})
                elif sn == "embedding":
                    merged["api_embedding_url"] = svc.get("url", "")
                    merged["embedding_model"] = svc.get("model", "")
            providers_dict[name] = merged
        raw["providers"] = providers_dict

        usages_dict: Dict[str, Any] = {}
        classification: Dict[str, Any] = {}
        for u in raw.get("usages", []):
            uname = u.get("name")
            if not uname:
                continue
            entry = {
                "template": u.get("template"),
                "assistant_role": u.get("assistantRole") or u.get("assistant_role"),
                "temperature": u.get("temperature", 0.3),
                "provider": u.get("provider"),
                "service": u.get("service"),
            }
            if uname in ("categoryClassification", "category_classification"):
                classification["category"] = entry
            elif uname in ("scenarioClassification", "scenario_classification"):
                classification["scenario"] = entry
            else:
                usages_dict[uname] = entry
        raw["usages"] = usages_dict
        if classification:
            raw["classification"] = classification
        return raw

    def _normalize_usages_array_only(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        usages_dict: Dict[str, Any] = {}
        classification: Dict[str, Any] = {}
        for u in raw.get("usages", []):
            uname = u.get("name")
            if not uname:
                continue
            entry = {
                "template": u.get("template"),
                "assistant_role": u.get("assistantRole") or u.get("assistant_role"),
                "temperature": u.get("temperature", 0.3),
                "provider": u.get("provider"),
                "service": u.get("service"),
            }
            if uname in ("categoryClassification", "category_classification"):
                classification["category"] = entry
            elif uname in ("scenarioClassification", "scenario_classification"):
                classification["scenario"] = entry
            else:
                usages_dict[uname] = entry
        raw["usages"] = usages_dict
        if classification:
            raw["classification"] = classification
        return raw

    def get_usage_config(self, usage_name: str) -> Dict[str, Any]:
        usages = self.config.get("usages", {})
        if usage_name not in usages:
            raise ValueError(f"Usage '{usage_name}' not found in configuration")
        return usages[usage_name]

    def get_prompt(self, usage_name: str, **template_vars: Any) -> str:
        usage_config = self.get_usage_config(usage_name)
        if "template" in usage_config:
            template_name = usage_config["template"]
            return render_prompt(template_name, **template_vars)
        if "prompt" in usage_config:
            prompt = usage_config["prompt"]
            for key, value in template_vars.items():
                prompt = prompt.replace(f"{{{{{key.upper()}}}}}", str(value))
            return prompt
        raise ValueError(f"No template or prompt found for usage '{usage_name}'")

    def get_classification_config(self, classifier_name: str) -> Dict[str, Any]:
        usages = self.config.get("usages", {})
        nested = usages.get("classification") if isinstance(usages, dict) else None
        if isinstance(nested, dict) and classifier_name in nested:
            return nested[classifier_name]
        classification = self.config.get("classification", {})
        if classifier_name not in classification:
            raise ValueError(f"Classifier '{classifier_name}' not found in configuration")
        return classification[classifier_name]

    def get_classification_prompt(self, classifier_name: str, **template_vars: Any) -> str:
        classifier_config = self.get_classification_config(classifier_name)
        if "template" in classifier_config:
            template_name = classifier_config["template"]
            return render_prompt(template_name, **template_vars)
        if "prompt" in classifier_config:
            prompt = classifier_config["prompt"]
            for key, value in template_vars.items():
                prompt = prompt.replace(f"{{{{{key.upper()}}}}}", str(value))
            return prompt
        raise ValueError(f"No template or prompt found for classifier '{classifier_name}'")

    def reload(self) -> None:
        self.config = self._load_config()
