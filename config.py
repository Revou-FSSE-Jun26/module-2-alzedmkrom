"""Application configuration."""

import os

from dotenv import load_dotenv

# Loads .env into the process environment. python-dotenv never overrides a
# variable already set (e.g. by the real shell/host env in production), so
# this is safe to call unconditionally.
load_dotenv()


class Config:
    """Configuration loaded with app.config.from_object(Config).

    Every value below is read from the environment (populated from `.env`
    for local development). There is no hardcoded fallback for
    `SQLALCHEMY_DATABASE_URI` or `SECRET_KEY`: a missing `.env` now fails
    loudly at startup instead of silently connecting to the wrong database
    or signing sessions with a well-known dev key.
    """

    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]

    # Turn off Flask-SQLAlchemy's event tracking to avoid its overhead warning.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ["SECRET_KEY"]

    # Parsed from the string env vars always are; anything other than a
    # literal "true" (case-insensitive) is treated as False.
    DEBUG = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"
