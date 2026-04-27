"""
Prompt template loader using Jinja2.

This module provides utilities to load and render prompt templates
from the config/prompts directory.
"""
import os
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Any


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class PromptTemplateLoader:
    """Loads and renders Jinja2 prompt templates."""
    
    def __init__(self):
        """
        Initialize the template loader.
        
        Args:
            templates_dir: Path to templates directory. 
                          Defaults to config/prompts/ relative to project root.
        """
        templates_dir = os.environ.get("PROMPTS_PATH", None)
        if templates_dir is None:
            raise RuntimeError("Missing required environment variable: PROMPTS_PATH")
        
        self.templates_dir = Path(templates_dir)
        
        if not self.templates_dir.exists():
            raise FileNotFoundError(
                f"Templates directory not found: {self.templates_dir}"
            )
        
        auto_reload = _env_bool("PROMPTS_AUTO_RELOAD", True)
        self._auto_reload = auto_reload
        self._last_logged_mtime: dict[str, float] = {}

        # Create Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
            auto_reload=auto_reload,
        )
    
    def render(self, template_name: str, **kwargs: Any) -> str:
        """
        Render a template with the given variables.
        
        Args:
            template_name: Name of the template file (e.g., 'summary.jinja2')
            **kwargs: Variables to pass to the template
        
        Returns:
            Rendered template string
        
        Raises:
            FileNotFoundError: If template doesn't exist
        """
        try:
            self._log_template_load(template_name)
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            raise FileNotFoundError(
                f"Error loading template '{template_name}': {str(e)}"
            )

    def _log_template_load(self, template_name: str) -> None:
        """
        Log when a template is (re)loaded from disk (based on file mtime).
        Includes the first few words of the template source for quick debugging.
        """
        try:
            path = (self.templates_dir / template_name).resolve()
            if not path.exists() or not path.is_file():
                return
            mtime = path.stat().st_mtime
            last = self._last_logged_mtime.get(template_name)
            if last is not None and mtime <= last:
                return
            self._last_logged_mtime[template_name] = mtime

            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return

            words = " ".join(raw.split())
            preview = " ".join(words.split()[:12])
            mode = "reload" if last is not None else "load"
            logger.info(
                "Prompt template %s: %s (%s...)",
                mode,
                template_name,
                preview,
            )
        except Exception:
            # Never block requests on logging.
            return
    
    def get_available_templates(self) -> list:
        """
        Get list of available template files.
        
        Returns:
            List of template filenames
        """
        return [f.name for f in self.templates_dir.glob("*.jinja2")]


# Global instance for easy access
_loader_instance = None


def get_template_loader() -> PromptTemplateLoader:
    """
    Get or create the global template loader instance.
    
    Returns:
        PromptTemplateLoader instance
    """
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = PromptTemplateLoader()
    return _loader_instance


def render_prompt(template_name: str, **kwargs: Any) -> str:
    """
    Convenience function to render a prompt template.
    
    Args:
        template_name: Name of the template file
        **kwargs: Variables to pass to the template
    
    Returns:
        Rendered prompt string
    """
    loader = get_template_loader()
    return loader.render(template_name, **kwargs)
