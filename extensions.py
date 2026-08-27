"""Flask application and shared extension instances.

Single import target for the rest of the project: every other module imports
``app`` and/or ``db`` from here, and nothing imports back into this module.
The only project import allowed here is ``Config`` from ``config``.
"""

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from config import Config

# Module-level app so Flask-Migrate and the flask CLI discover it directly.
app = Flask(__name__)
app.config.from_object(Config)

# Direct bound form: the extensions are attached to the app on creation.
db = SQLAlchemy(app)
migrate = Migrate(app, db)
