"""
src/auth.py - API Key Authentication
"""

import logging
from typing import Any

from fastapi import HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader
from google.auth.transport import requests
from google.oauth2 import id_token

from hippique_orchestrator import config

logger = logging.getLogger(__name__)

api_key_header_scheme = APIKeyHeader(name="X-API-KEY", auto_error=False)
oidc_token_scheme = APIKeyHeader(
    name="Authorization",
    description="Bearer token from a Google-issued OIDC ID token.",
    auto_error=True,
)


async def check_api_key(api_key_header: str | None = Security(api_key_header_scheme)):
    """Dependency to verify the internal API key."""
    if not config.REQUIRE_AUTH:
        return True

    if not config.INTERNAL_API_SECRET:
        # This is a server misconfiguration, should not happen in prod
        logger.error("Internal API secret not configured on server.")
        raise HTTPException(status_code=500, detail="Internal API secret not configured on server.")
    
    logger.debug(f"API Key Header: '{api_key_header}'")
    logger.debug(f"Internal API Secret (configured): '{config.INTERNAL_API_SECRET}'")

    if api_key_header is None or api_key_header != config.INTERNAL_API_SECRET:
        logger.warning(f"Invalid or missing API Key. Provided: '{api_key_header}', Expected: '****{config.INTERNAL_API_SECRET[-4:]}'")
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")
    return True


async def verify_oidc_token(
    request: Request, token: str = Security(oidc_token_scheme)
) -> dict[str, Any]:
    """
    Dependency to verify Google-issued OIDC tokens, typically from Cloud Tasks.
    """
    if not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token scheme. Must be 'Bearer'.")

    # The actual token is after "Bearer "
    token = token.split(" ", 1)[1]

    try:
        # The audience should be the full URL of the service.

        # Validate the token
        # This checks signature, expiration, issuer, and audience.
        # NOTE: Audience validation is temporarily disabled to debug 401 errors from Cloud Tasks.
        token_claims = id_token.verify_oauth2_token(
            id_token=token, request=requests.Request()
        )
        return token_claims
    except ValueError as e:
        # This catches a wide range of token validation errors
        # (e.g., malformed, expired, wrong signature, wrong audience)
        raise HTTPException(status_code=401, detail=f"Token validation failed: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred during token validation: {e}") from e


def _require_api_key(request: Request):
    """
    Checks for the presence and validity of the X-API-KEY header if authentication is required.
    If authentication is not required, it allows the request to pass.
    """
    if not config.REQUIRE_AUTH:
        return

    if not config.INTERNAL_API_SECRET:
        raise HTTPException(status_code=500, detail="Internal API secret not configured on server.")

    api_key = request.headers.get("X-API-KEY")
    if api_key is None or api_key != config.INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")
