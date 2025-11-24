"""
Routes package for SquidStats application.
Contains all route blueprints organized by functionality.
"""

from .admin_routes import admin_bp
from .api_routes import api_bp
from .logs_routes import logs_bp
from .main_routes import main_bp
from .reports_routes import reports_bp
from .stats_routes import stats_bp


def register_routes(app):
    """Register all blueprints with the Flask application."""
    app.register_blueprint(main_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(stats_bp)
