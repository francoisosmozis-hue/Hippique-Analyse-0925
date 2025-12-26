"""
src/auth.py - API Key Authentication
"""
from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from hippique_orchestrator import config

api_key_header_scheme = APIKeyHeader(name="X-API-KEY", auto_error=True)

async def check_api_key(api_key_header: str = Security(api_key_header_scheme)):
    """Dependency to verify the internal API key."""
    if not config.INTERNAL_API_SECRET:
        # This is a server misconfiguration, should not happen in prod
        raise HTTPException(status_code=500, detail="Internal API secret not configured on server.")
    
    if api_key_header != config.INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")
    return True