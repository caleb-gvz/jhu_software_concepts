from flask import Flask


def create_app():
    """Application factory: builds and configures the Flask app."""
    app = Flask(__name__)

    # Register the blueprint that holds all our page routes.
    from app.routes import main
    app.register_blueprint(main)

    return app
