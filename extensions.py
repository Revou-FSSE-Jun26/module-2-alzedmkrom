"""Flask application and shared extension instances.

Single import target for the rest of the project: every other module imports
``app`` and/or ``db`` from here, and nothing imports back into this module.
The only project import allowed here is ``Config`` from ``config``.
"""

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

# Module-level app so Flask-Migrate and the flask CLI discover it directly.
app = Flask(__name__)
app.config.from_object(Config)

# Recover the real client address from X-Forwarded-For before anything reads
# it. Rate limiting keys on the client IP, and behind a platform proxy
# `request.remote_addr` is the proxy, which would put every visitor in one
# bucket — one person's failed logins would then lock out everyone.
#
# Only `TRUSTED_PROXY_COUNT` entries are trusted, counted from the right, so a
# client cannot prepend a forged entry to win itself a fresh quota. Skipped
# entirely when that count is 0, which is the correct setting with no proxy in
# front (trusting the header then would mean trusting the client).
if app.config["TRUSTED_PROXY_COUNT"] > 0:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=app.config["TRUSTED_PROXY_COUNT"],
        x_proto=app.config["TRUSTED_PROXY_COUNT"],
        x_host=app.config["TRUSTED_PROXY_COUNT"],
    )

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

# Request rate limiting, keyed on the client IP.
#
# Primarily an anti-brute-force measure rather than a capacity control: the
# role checks in ``auth.py`` are worth nothing if an attacker can simply guess
# an admin's password, and guessing is only expensive if attempts are capped.
# Per-endpoint limits are applied by decorator in ``routes.py``; the settings
# themselves live in ``Config``, and the 429 response is shaped into this
# project's JSON envelope by ``errors.py``.
# Built unconditionally enabled so its storage backend is always initialised,
# then switched to the state the environment asked for. Flask-Limiter skips
# storage setup when it starts disabled, which would leave a limiter that
# cannot be turned on later — and the test suite does exactly that, running
# with limits off and enabling them per test. See the note on
# ``RATELIMIT_ENABLED`` in config.py.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[app.config["RATELIMIT_DEFAULT"]],
    storage_uri=app.config["RATELIMIT_STORAGE_URI"],
)
limiter.enabled = app.config["RATE_LIMITING_ACTIVE"]
