"""Application configuration."""

import os


class Config:
    """Configuration loaded with app.config.from_object(Config)."""

    # Connection to the local revoshop_db PostgreSQL database.
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:alzedsql22@localhost/revoshop_db"

    # Turn off Flask-SQLAlchemy's event tracking to avoid its overhead warning.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Used by Flask for signing. Override with SECRET_KEY in the environment.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
