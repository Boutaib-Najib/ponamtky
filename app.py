from flask import Flask, jsonify
from dotenv import load_dotenv

from ai import news_classifier_bp


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    app.register_blueprint(news_classifier_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5009, debug=True)
