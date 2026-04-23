"""Shared upload validation/storage helpers for read=UPLOAD endpoints."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from werkzeug.datastructures import FileStorage


_ALLOWED_SUFFIXES = {".txt", ".pdf"}
_DEFAULT_MAX_UPLOAD_MB = 20


@dataclass
class SavedUpload:
    path: Path
    original_filename: str


def _stream_size(file: FileStorage) -> Optional[int]:
    try:
        current = file.stream.tell()
        file.stream.seek(0, 2)
        size = file.stream.tell()
        file.stream.seek(current)
        return size
    except Exception:
        return None


def save_validated_upload(
    file: Optional[FileStorage], max_upload_mb: int = _DEFAULT_MAX_UPLOAD_MB
) -> Tuple[Optional[SavedUpload], Optional[str]]:
    if file is None or not file.filename:
        return None, "File upload is required for read=3."

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        return None, "Unsupported file type. Only .txt and .pdf are allowed."

    max_bytes = max_upload_mb * 1024 * 1024
    size = _stream_size(file)
    if size is not None and size > max_bytes:
        return None, f"File too large. Maximum size is {max_upload_mb}MB."

    # Peek file signature/content before saving.
    file.stream.seek(0)
    head = file.stream.read(8192)
    file.stream.seek(0)

    if suffix == ".pdf":
        if not head.startswith(b"%PDF-"):
            return None, "Invalid PDF signature."
    elif suffix == ".txt":
        if b"\x00" in head:
            return None, "Invalid text file content."

    tmp_dir = Path(tempfile.gettempdir()) / "ponamtky_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"{uuid4()}{suffix}"
    file.save(str(path))
    return SavedUpload(path=path, original_filename=file.filename), None

