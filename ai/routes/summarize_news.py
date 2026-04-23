"""POST /api/news-classifier/summarize-news"""

import os

from flask import jsonify, request

from ..blueprint import news_classifier_bp
from ..deps import get_ia
from ..enums import ReadMode
from ..uploads import save_validated_upload
from ..validators import PayloadValidationError, parse_summarize_payload


@news_classifier_bp.post("/summarize-news")
def summarize_news():
    is_multipart = request.content_type and "multipart/form-data" in request.content_type
    data = request.form.to_dict() if is_multipart else request.get_json(silent=True)
    try:
        payload = parse_summarize_payload(data)
    except PayloadValidationError as exc:
        return jsonify({"errors": exc.errors}), 400

    saved_upload = None
    try:
        if payload.read == ReadMode.UPLOAD:
            if not is_multipart:
                return jsonify(
                    {
                        "errors": [
                            {
                                "field": "body",
                                "message": "For read=3, use multipart/form-data with file field 'file'.",
                            }
                        ]
                    }
                ), 400

            saved_upload, upload_error = save_validated_upload(request.files.get("file"))
            if upload_error:
                return jsonify({"errors": [{"field": "file", "message": upload_error}]}), 400

        result = get_ia().summarize_news_spec(
            read=payload.read.value,
            url=payload.url,
            text=payload.text,
            upload_file_path=str(saved_upload.path) if saved_upload else None,
            upload_filename=saved_upload.original_filename if saved_upload else None,
            force_playwright=False,
        )
        return jsonify(result)
    finally:
        if saved_upload and saved_upload.path.exists():
            try:
                os.remove(saved_upload.path)
            except OSError:
                pass
