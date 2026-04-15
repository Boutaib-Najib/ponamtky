"""Register news-classifier HTTP routes (one module per endpoint)."""

from . import classify_news  # noqa: F401
from . import summarize_news  # noqa: F401
