"""POST /api/news-classifier/summarize-news"""

from flask import jsonify, request

from ..blueprint import news_classifier_bp
from ..deps import get_ia
from ..validators import PayloadValidationError, parse_summarize_payload


@news_classifier_bp.post("/summarize-news")
def summarize_news():
    data = request.get_json(silent=True)
    try:
        payload = parse_summarize_payload(data)
    except PayloadValidationError as exc:
        return jsonify({"errors": exc.errors}), 400

    result = get_ia().summarize_news_spec(
        read=payload.read.value,
        url=payload.url,
        text=payload.text,
        force_playwright=False,
    )
    return jsonify(result)
