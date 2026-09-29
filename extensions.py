"""Flask application and shared extension instances.

Single import target for the rest of the project: every other module imports
``app`` and/or ``db`` from here, and nothing imports back into this module.
The only project import allowed here is ``Config`` from ``config``.
"""

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from config import Config

# Module-level app so Flask-Migrate and the flask CLI discover it directly.
app = Flask(__name__)
app.config.from_object(Config)

# Direct bound form: the extensions are attached to the app on creation.
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Cross-origin access for browser frontends. Scoped to the origins in
# `Config.CORS_ORIGINS` (an explicit allowlist, not "*") and applied to every
# route, since every route in this project is an API endpoint. `supports_
# credentials` stays off: there is no cookie-based session to send, and it is
# incompatible with a wildcard origin should the allowlist ever be widened.
cors = CORS(
    app,
    resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}},
    supports_credentials=False,
)

# JWT access/refresh tokens. The manager is created here, but its callbacks
# (blocklist check, user loader, and the JSON error responses) live in
# ``auth.py``, which imports this object — the same import-side-effect pattern
# ``errors.py`` uses, and the reason ``app.py`` imports ``auth``.
jwt = JWTManager(app)
