"""JSON error handlers.

Registered on the module-level ``app`` by import side effect, so every failure
leaves the application as the same ``{"error": ..., "message": ...}`` envelope
instead of a Werkzeug HTML error page. That matters because every route in this
project is an API endpoint: a client that gets HTML back on a 404 cannot parse
the failure.

The only project import here is ``app`` from ``extensions``.
"""

from flask import jsonify
from werkzeug.exceptions import HTTPException

from extensions import app

# Fallback messages used when the raising code supplied no description of its
# own. Keys are the HTTP status codes handled below.
_DEFAULT_MESSAGES = {
    400: "The request could not be understood. A valid JSON body is required.",
    404: "The requested resource was not found.",
    405: "The HTTP method is not allowed for this URL.",
    500: "An internal error occurred. Please try again later.",
}

_DEFAULT_NAMES = {
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
}


def _error_name(error, status_code):
    """Human-readable status name, preferring Werkzeug's own for HTTPExceptions."""
    name = getattr(error, "name", None)
    if isinstance(error, HTTPException) and name:
        return name
    return _DEFAULT_NAMES[status_code]


def _error_message(error, status_code):
    """Honor a route-supplied description, otherwise use the generic message.

    ``abort(404, description="User 999 was not found.")`` sets ``description``
    on the instance, while the unaltered default lives on the exception class.
    Comparing the two is what distinguishes a deliberate message from
    Werkzeug's boilerplate.
    """
    description = getattr(error, "description", None)
    class_default = getattr(type(error), "description", None)
    if description and description != class_default:
        return description
    return _DEFAULT_MESSAGES[status_code]


def _json_error(error, status_code):
    """Build the shared error envelope."""
    payload = {
        "error": _error_name(error, status_code),
        "message": _error_message(error, status_code),
    }
    return jsonify(payload), status_code


@app.errorhandler(400)
def bad_request(error):
    """Malformed or invalid request, including a missing or non-JSON body."""
    return _json_error(error, 400)


@app.errorhandler(404)
def not_found(error):
    """Unknown URL, or a route aborting because a record does not exist."""
    return _json_error(error, 404)


@app.errorhandler(405)
def method_not_allowed(error):
    """Known URL, wrong HTTP method."""
    return _json_error(error, 405)


@app.errorhandler(500)
def internal_server_error(error):
    """Unexpected server-side failure, including database errors.

    The detail is logged server-side and never returned, so internal messages
    and the connection string cannot leak to a client. The response is always
    the generic message regardless of any description on the exception.
    """
    detail = getattr(error, "original_exception", None) or error
    app.logger.exception("Unhandled server error: %s", detail)

    payload = {
        "error": _DEFAULT_NAMES[500],
        "message": _DEFAULT_MESSAGES[500],
    }
    return jsonify(payload), 500
