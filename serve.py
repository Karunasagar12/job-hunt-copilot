"""Production entrypoint for serving the Flask API and dashboard."""
import os

from waitress import serve

from api.app import app


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threads=4)
