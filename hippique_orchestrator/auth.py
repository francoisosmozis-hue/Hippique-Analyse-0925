"""
src/auth.py - API Key Authentication
"""

from __future__ import annotations

from fastapi import HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader
from google.auth.transport import requests
from google.oauth2 import id_token

from hippique_orchestrator import config

api_key_header_scheme = APIKeyHeader(name="X-API-KEY", auto_error=True)
oidc_token_scheme = APIKeyHeader(
    name="Authorization",
    description="Bearer token from a Google-issued OIDC ID token.",
    auto_error=True,
)


async def check_api_key(api_key_header: str = Security(api_key_header_scheme)):
    """Dependency to verify the internal API key."""
    if not config.INTERNAL_API_SECRET:
        # This is a server misconfiguration, should not happen in prod
        raise HTTPException(status_code=500, detail="Internal API secret not configured on server.")

    if api_key_header != config.INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key.")
    return True


async def verify_oidc_token(
    request: Request, token: str = Security(oidc_token_scheme)
) -> dict[str, any]:
    """
    Dependency to verify Google-issued OIDC tokens, typically from Cloud Tasks.
    """
    if not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token scheme. Must be 'Bearer'.")

    # The actual token is after "Bearer "
    token = token.split(" ", 1)[1]

    try:
        # The audience should be the full URL of the service.
        # We derive it from the request headers.
        audience = f"{request.url.scheme}://{request.url.netloc}/"

        # Validate the token
        # This checks signature, expiration, issuer, and audience.
        token_claims = id_token.verify_oauth2_token(
            id_token=token, request=requests.Request(), audience=audience
        )
        return token_claims
    except ValueError as e:
        # This catches a wide range of token validation errors
        # (e.g., malformed, expired, wrong signature, wrong audience)
        raise HTTPException(status_code=401, detail=f"Token validation failed: {e}") from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred during token validation: {e}"
        ) from e
