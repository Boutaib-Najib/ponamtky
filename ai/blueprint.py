from flask import Blueprint, jsonify, request

from .auth import extract_api_key, get_key_store

news_classifier_bp = Blueprint(
    "news_classifier",
    __name__,
    url_prefix="/api/news-classifier",
)


@news_classifier_bp.before_request
def _require_api_key():
    store = get_key_store()
    token = extract_api_key(request.headers)
    if store.is_allowed(token):
        return None
    return (
        jsonify(
            {
                "errors": [
                    {
                        "field": "x-auth-api-key",
                        "message": "Unauthorized",
                    }
                ]
            }
        ),
        401,
    )
