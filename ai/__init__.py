from .blueprint import news_classifier_bp

# Import route modules so handlers attach to the blueprint
from . import routes  # noqa: F401

__all__ = ["news_classifier_bp"]
