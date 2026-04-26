"""Payload validation for news-classifier endpoints."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from shared.enums import Policy, ReadMode


@dataclass
class SummarizePayload:
    read: ReadMode
    url: Optional[str]
    text: Optional[str]
    provider: Optional[str]


@dataclass
class ClassifyPayload:
    read: ReadMode
    policy: Policy
    url: Optional[str]
    text: Optional[str]
    category: Optional[str]
    provider: Optional[str]


class PayloadValidationError(Exception):
    """Raised when request JSON fails validation."""

    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        super().__init__(str(errors))


def _append(errors: List[Dict[str, str]], field: str, message: str) -> None:
    errors.append({"field": field, "message": message})


def _parse_read_mode(raw: Any, errors: List[Dict[str, str]]) -> Optional[ReadMode]:
    if raw is None:
        _append(errors, "read", "Field 'read' is required.")
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _append(errors, "read", "Field 'read' must be an integer (1, 2, or 3).")
        return None
    try:
        return ReadMode(value)
    except ValueError:
        _append(
            errors,
            "read",
            "Field 'read' must be one of: 1 (from URL), 2 (from text), 3 (upload).",
        )
        return None


def _parse_policy(
    raw: Any, errors: List[Dict[str, str]], default: Policy
) -> Optional[Policy]:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _append(errors, "policy", "Field 'policy' must be an integer (0, 1, or 2).")
        return None
    try:
        return Policy(value)
    except ValueError:
        _append(
            errors,
            "policy",
            "Field 'policy' must be one of: 0 (category only), 1 (scenario only), 2 (both).",
        )
        return None


def _is_blank_str(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s if s else None


def _validate_url_field(url: Optional[str], errors: List[Dict[str, str]]) -> None:
    if url is None:
        _append(errors, "url", "Field 'url' is required when read is 1 (from URL).")
        return
    if _is_blank_str(url):
        _append(errors, "url", "Field 'url' must be a non-empty string.")
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        _append(errors, "url", "Field 'url' must be a valid http or https URL.")


def _validate_text_field(text: Optional[str], errors: List[Dict[str, str]]) -> None:
    if text is None:
        _append(errors, "text", "Field 'text' is required when read is 2 (from text).")
        return
    if _is_blank_str(text):
        _append(errors, "text", "Field 'text' must be a non-empty string.")


def parse_summarize_payload(data: Any) -> SummarizePayload:
    errors: List[Dict[str, str]] = []
    if data is None:
        _append(errors, "body", "Request body must be a JSON object.")
        raise PayloadValidationError(errors)
    if not isinstance(data, dict):
        _append(errors, "body", "Request body must be a JSON object.")
        raise PayloadValidationError(errors)

    read = _parse_read_mode(data.get("read"), errors)
    url = _optional_str(data.get("url"))
    provider_raw = data.get("provider")
    provider = _optional_str(provider_raw)
    if provider_raw is not None and not isinstance(provider_raw, str):
        _append(errors, "provider", "Field 'provider' must be a string when provided.")
    text = data.get("text")
    if text is not None and not isinstance(text, str):
        _append(errors, "text", "Field 'text' must be a string when provided.")
        text = None
    elif isinstance(text, str):
        text = text  # may be empty; validated per read mode

    if read is not None:
        if read == ReadMode.FROM_URL:
            _validate_url_field(url, errors)
        elif read == ReadMode.FROM_TEXT:
            _validate_text_field(text if isinstance(text, str) else None, errors)

    if errors:
        raise PayloadValidationError(errors)

    assert read is not None
    return SummarizePayload(
        read=read,
        url=url,
        text=text if isinstance(text, str) else None,
        provider=provider,
    )


def parse_classify_payload(data: Any) -> ClassifyPayload:
    errors: List[Dict[str, str]] = []
    if data is None:
        _append(errors, "body", "Request body must be a JSON object.")
        raise PayloadValidationError(errors)
    if not isinstance(data, dict):
        _append(errors, "body", "Request body must be a JSON object.")
        raise PayloadValidationError(errors)

    read = _parse_read_mode(data.get("read"), errors)
    policy = _parse_policy(data.get("policy"), errors, Policy.CATEGORY_AND_SCENARIO)

    url = _optional_str(data.get("url"))
    text = data.get("text")
    provider_raw = data.get("provider")
    provider = _optional_str(provider_raw)
    if provider_raw is not None and not isinstance(provider_raw, str):
        _append(errors, "provider", "Field 'provider' must be a string when provided.")
    if text is not None and not isinstance(text, str):
        _append(errors, "text", "Field 'text' must be a string when provided.")
        text = None

    category_raw = data.get("category")
    category: Optional[str] = None
    if category_raw is not None:
        if not isinstance(category_raw, str):
            _append(errors, "category", "Field 'category' must be a string when provided.")
        else:
            category = category_raw.strip() or None

    if read is not None:
        if read == ReadMode.FROM_URL:
            _validate_url_field(url, errors)
        elif read == ReadMode.FROM_TEXT:
            _validate_text_field(text if isinstance(text, str) else None, errors)

    if policy == Policy.SCENARIO_ONLY and not category:
        _append(
            errors,
            "category",
            "Field 'category' is required when policy is 1 (scenario only).",
        )

    if errors:
        raise PayloadValidationError(errors)

    assert read is not None and policy is not None
    return ClassifyPayload(
        read=read,
        policy=policy,
        url=url,
        text=text if isinstance(text, str) else None,
        category=category,
        provider=provider,
    )
