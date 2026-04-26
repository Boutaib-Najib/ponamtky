"""Shared enums used by API and core modules."""

from enum import IntEnum


class ReadMode(IntEnum):
    """How document content is provided (``read`` field)."""

    FROM_URL = 1
    FROM_TEXT = 2
    UPLOAD = 3


class Policy(IntEnum):
    """Classification depth (``policy`` field on classify)."""

    CATEGORY_ONLY = 0
    SCENARIO_ONLY = 1
    CATEGORY_AND_SCENARIO = 2
