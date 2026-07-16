"""Flask entrypoint. Initialises DB on boot, registers blueprint."""
from flask import Flask, jsonify
from flask_cors import CORS

import config
from db import Base, engine
from routes.http import api
from routes.internal import internal


def create_app() -> Flask:
    app = Flask(__name__)
    # The /api/* origin CORS is permissive for the operator UI. The
    # /api/internal/* routes are HMAC-gated (no CORS preflight reaches them
    # in normal use — only the Worker calls them server-to-server).
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Models register with metadata on import
    import models  # noqa: F401

    Base.metadata.create_all(engine)

    app.register_blueprint(api)
    app.register_blueprint(internal)

    @app.get("/")
    def root():
        return jsonify({
            "service": "acme-finance-suite",
            "ok": True,
            "endpoints": [
                "/api/health",
                "/api/dashboard",
                "/api/invoices",
                "/api/payouts",
                "/api/ledger/entries",
                "/api/receipts",
                "/api/mileage",
                "/api/tax/schedule-c?year=2026",
                "/api/merch/products",
                "/api/internal/health (HMAC)",
                "/api/internal/customers/upsert (HMAC)",
                "/api/internal/invoices/create (HMAC)",
            ],
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=True, use_reloader=False)
