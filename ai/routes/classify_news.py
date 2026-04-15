"""POST /api/news-classifier/classify-news"""

from flask import jsonify, request

from ..blueprint import news_classifier_bp
from ..deps import get_ia
from ..validators import PayloadValidationError, parse_classify_payload


@news_classifier_bp.post("/classify-news")
def classify_news():
    data = request.get_json(silent=True)
    try:
        payload = parse_classify_payload(data)
    except PayloadValidationError as exc:
        return jsonify({"errors": exc.errors}), 400

    result = get_ia().classify_news_spec(
        read=payload.read.value,
        policy=payload.policy.value,
        url=payload.url,
        text=payload.text,
        category=payload.category,
        force_playwright=False,
    )
    return jsonify(result)
