"""Application entry point.

Imports the module-level ``app``, registers the blueprints explicitly so the URL
wiring is readable in one place, and imports the modules that register through
import side effects. Nothing imports this module, which is what keeps the import
graph acyclic and lets every launch path work:

    python app.py       runs the __main__ block below (debug from the call)
    flask run           imports this module and finds the `app` attribute
    flask db ...        same discovery, via FLASK_APP in .flaskenv
    flask check-db      same discovery
"""

from extensions import app
from routes import products_bp, users_bp

# Imported for their registration side effects, not for any name they export:
#   models  puts the tables on db.metadata so Alembic autogenerate sees them
#   errors  registers the JSON error handlers on `app`
#   cli     registers the custom `flask` commands on `app`
import models  # noqa: F401
import errors  # noqa: F401
import cli  # noqa: F401

app.register_blueprint(products_bp)
app.register_blueprint(users_bp)


if __name__ == "__main__":
    app.run(debug=True)
