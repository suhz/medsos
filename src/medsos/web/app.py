"""Flask app factory."""
from __future__ import annotations

from flask import Flask

from medsos.web.accounts import bp as accounts_bp
from medsos.web.health import bp as health_bp
from medsos.web.webhooks import bp as webhooks_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(accounts_bp)
    return app