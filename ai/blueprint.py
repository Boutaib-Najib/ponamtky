from flask import Blueprint

news_classifier_bp = Blueprint(
    "news_classifier",
    __name__,
    url_prefix="/api/news-classifier",
)
