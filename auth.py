"""JWT wiring: token identity, revocation checks, guards, and JSON failures.

Registered on the module-level ``jwt`` manager by import side effect, the same
way ``errors.py`` registers its handlers, which is why ``app.py`` imports this
module without using any name from it.

Two things here matter to a frontend:

1. **Every authentication failure is JSON**, matching the ``{"error",
   "message"}`` envelope the rest of the API uses, plus a machine-readable
   ``code``. Flask-JWT-Extended's defaults would otherwise return their own
   shape for some failures and Werkzeug HTML for others.

2. **The ``code`` distinguishes the two 401s that mean different things.**
   ``token_expired`` on a normal request means "the access token aged out,
   call ``POST /auth/refresh`` and retry" — the user should notice nothing.
   ``token_expired`` from ``/auth/refresh`` itself (or ``token_revoked``)
   means the session is over: clear both tokens and show the login screen.
   That second case is the auto-logout.
"""

from datetime import datetime, timezone
from functools import wraps

from flask import jsonify
from flask_jwt_extended import current_user, get_jwt, verify_jwt_in_request

from extensions import app, db, jwt
from models import TokenBlocklist, User

# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


def _auth_error(code, message, status=401, **extra):
    """Build the shared auth failure response.

    ``code`` is the stable, machine-readable part: clients branch on it rather
    than on ``message``, which is free to be reworded. ``extra`` adds further
    top-level keys (used to echo the token type on an expiry).
    """
    payload = {
        "error": "Unauthorized" if status == 401 else "Forbidden",
        "message": message,
        "code": code,
    }
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Identity: token <-> User
# ---------------------------------------------------------------------------


@jwt.user_identity_loader
def _user_identity(user):
    """Serialize whatever a route passed as ``identity`` into the ``sub`` claim.

    Routes hand over a ``User`` (or a bare id); the JWT spec requires ``sub``
    to be a string, and Flask-JWT-Extended 4.x enforces that, so the id is
    stringified here rather than at every call site.
    """
    if isinstance(user, User):
        return str(user.id)
    return str(user)


@jwt.user_lookup_loader
def _user_lookup(_jwt_header, jwt_data):
    """Resolve ``sub`` back into a ``User`` for ``current_user``.

    Returning ``None`` makes Flask-JWT-Extended call
    ``user_lookup_error_loader`` below, which is what rejects a token whose
    account has since been deleted **or deactivated**. Checking
    ``is_active`` here (rather than only at login) is what stops an
    already-issued token from outliving the account being disabled.
    """
    identity = jwt_data.get("sub")
    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return None

    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


@jwt.token_in_blocklist_loader
def _token_revoked(_jwt_header, jwt_data):
    """Return whether this token's ``jti`` has been revoked.

    Runs on every authenticated request, which is why ``token_blocklist.jti``
    is indexed.
    """
    jti = jwt_data.get("jti")
    if not jti:
        return True
    return (
        db.session.query(TokenBlocklist.id).filter_by(jti=jti).first() is not None
    )


def revoke_current_token():
    """Add the token used by the current request to the blocklist.

    Reads the decoded token off the request context, so it must be called
    inside a route that has already verified a JWT. Idempotent: revoking an
    already-revoked jti is a no-op rather than a unique-constraint error.
    """
    decoded = get_jwt()
    return revoke_token(decoded)


def revoke_token(decoded):
    """Blocklist an already-decoded token. Safe to call twice on one token."""
    jti = decoded["jti"]
    existing = db.session.query(TokenBlocklist.id).filter_by(jti=jti).first()
    if existing is not None:
        return False

    db.session.add(
        TokenBlocklist(
            jti=jti,
            token_type=decoded.get("type", "access"),
            user_id=int(decoded["sub"]),
            expires_at=datetime.fromtimestamp(decoded["exp"], tz=timezone.utc),
        )
    )
    return True


# ---------------------------------------------------------------------------
# Failure callbacks
# ---------------------------------------------------------------------------


@jwt.expired_token_loader
def _expired_token(_jwt_header, jwt_data):
    """A structurally valid token whose `exp` has passed.

    The token type is echoed so a client can tell the recoverable case
    (``"access"`` -> refresh and retry) from the terminal one
    (``"refresh"`` -> the session is over, log out).
    """
    token_type = jwt_data.get("type", "access")
    if token_type == "refresh":
        message = "Session expired. Please log in again."
    else:
        message = "Access token expired. Use POST /auth/refresh to obtain a new one."
    return _auth_error("token_expired", message, token_type=token_type)


@jwt.revoked_token_loader
def _revoked_token(_jwt_header, _jwt_data):
    """A token that was explicitly logged out, or a refresh token already rotated."""
    return _auth_error(
        "token_revoked",
        "This token has been revoked. Please log in again.",
    )


@jwt.invalid_token_loader
def _invalid_token(reason):
    """Malformed token, bad signature, or the wrong token type for the route."""
    return _auth_error("token_invalid", f"Invalid token: {reason}")


@jwt.unauthorized_loader
def _missing_token(reason):
    """No `Authorization: Bearer <token>` header at all on a protected route."""
    return _auth_error(
        "authorization_required",
        f"Authentication is required to access this resource. {reason}",
    )


@jwt.needs_fresh_token_loader
def _needs_fresh_token(_jwt_header, _jwt_data):
    """Reserved for routes that demand a freshly-issued token."""
    return _auth_error(
        "fresh_token_required",
        "A freshly issued token is required for this action. Please log in again.",
    )


@jwt.user_lookup_error_loader
def _user_lookup_error(_jwt_header, _jwt_data):
    """The token verified, but its subject no longer resolves to a usable account."""
    return _auth_error(
        "user_unavailable",
        "The account for this token no longer exists or has been deactivated.",
    )


# ---------------------------------------------------------------------------
# Guards used by routes.py
# ---------------------------------------------------------------------------


def is_admin(user):
    """Whether `user` holds the configured admin role (case-insensitive).

    Tolerates being handed the ``current_user`` proxy on a route that used
    ``@jwt_required(optional=True)`` and received no token. A ``LocalProxy``
    wrapping ``None`` is not itself ``None``, so an ``is None`` check would
    pass and then blow up on attribute access; reading the attribute and
    catching the failure is what actually distinguishes "no caller" here.
    """
    try:
        role = user.role
    except (AttributeError, RuntimeError):
        return False
    if not role:
        return False
    return role.strip().lower() == app.config["ADMIN_ROLE"].strip().lower()


def admin_required(fn):
    """Require a valid access token **and** the admin role.

    Deliberately two distinct statuses: a caller with no/expired token gets
    401 (authenticate, then retry), while a valid but non-admin caller gets
    403 (authenticated fine, not allowed — retrying will not help).
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        if not is_admin(current_user):
            return _auth_error(
                "admin_required",
                "This action requires administrator privileges.",
                status=403,
            )
        return fn(*args, **kwargs)

    return wrapper


def forbid_unless_self_or_admin(user_id):
    """Guard for per-user resources: owner or admin only.

    Returns ``None`` when the caller may proceed, or a ready-to-return 403
    response when they may not. Used by the order and user routes so a logged-
    in customer cannot read or delete somebody else's records by guessing ids.
    """
    if current_user.id == user_id or is_admin(current_user):
        return None
    return _auth_error(
        "forbidden",
        "You do not have permission to access this resource.",
        status=403,
    )
