"""Uvicorn entrypoint: `uvicorn app.main:app --reload`."""

from app.infrastructure.config import Settings
from app.interfaces.api.app import create_app

app = create_app(Settings())
