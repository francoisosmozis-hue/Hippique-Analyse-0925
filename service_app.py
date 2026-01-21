"""
service_app.py - Application entry point.

This module serves as the entry point for ASGI servers like uvicorn and for test runners.
It imports the FastAPI app instance and the app factory from the main service module.
"""

from hippique_orchestrator.service import create_app

app = create_app()

__all__ = ["app", "create_app"]
