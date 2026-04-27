import os

from flask import Flask, jsonify
from dotenv import load_dotenv

from core.logging_config import configure_logging


def create_app() -> Flask:
    load_dotenv()
    configure_logging()

    app = Flask(__name__)
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "20"))
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(413)
    def request_entity_too_large(_):
        return jsonify(
            {
                "errors": [
                    {
                        "field": "file",
                        "message": f"File too large. Maximum size is {max_upload_mb}MB.",
                    }
                ]
            }
        ), 413

    # Import after logging/.env are configured so startup logs are formatted
    # and env-dependent initialization (providers, prompts) sees the right env.
    from ai import news_classifier_bp

    app.register_blueprint(news_classifier_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5009, debug=True)
