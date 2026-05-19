import os
import sys

# Add repo root to Python path so `app` package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mangum import Mangum
from app.main import app
from app.db import init_db

# Initialise DB schema and seed data on cold start
init_db()

_handler = Mangum(app, lifespan="off")


def handler(event, context):
    return _handler(event, context)
