"""ASGI entry point for cloud deployment (Render, Railway, Gunicorn/Uvicorn)."""
from api.app import app

__all__ = ["app"]
