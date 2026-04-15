"""
Module d'initialisation pour le package core
"""

from .ia import IA
from .config_manager import ConfigManager
from .utils import (
    is_empty,
    chunk_text_by_words,
    trim_to_word_limit,
    count_words,
    extract_json_from_text,
    clean_whitespace
)

__all__ = [
    'IA',
    'ConfigManager',
    'is_empty',
    'chunk_text_by_words',
    'trim_to_word_limit',
    'count_words',
    'extract_json_from_text',
    'clean_whitespace'
]
