"""
Prompt template loader using Jinja2.

This module provides utilities to load and render prompt templates
from the config/prompts directory.
"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Dict, Any


class PromptTemplateLoader:
    """Loads and renders Jinja2 prompt templates."""
    
    def __init__(self, templates_dir: Path = None):
        """
        Initialize the template loader.
        
        Args:
            templates_dir: Path to templates directory. 
                          Defaults to config/prompts/ relative to project root.
        """
        if templates_dir is None:
            # Get project root (two levels up from core/)
            # In this repo, core/ lives directly under the project root.
            project_root = Path(__file__).resolve().parent.parent
            templates_dir = project_root / "config" / "prompts"
        
        self.templates_dir = Path(templates_dir)
        
        if not self.templates_dir.exists():
            raise FileNotFoundError(
                f"Templates directory not found: {self.templates_dir}"
            )
        
        # Create Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
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
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            raise FileNotFoundError(
                f"Error loading template '{template_name}': {str(e)}"
            )
    
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
