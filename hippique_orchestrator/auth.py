"""
src/auth.py - OIDC Authentication Middleware
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests
from google.oauth2 import id_token

from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)
config = get_config()

# Use a custom scheme to clearly identify OIDC tokens in documentation
oidc_scheme = HTTPBearer(scheme_name="OIDC Token")

class OIDCValidator:
    """
    Validates Google OIDC tokens.
    """

    def __init__(self, audience: str):
        if not audience:
            raise ValueError("OIDC audience must be configured.")
        self.audience = audience
        self.request = requests.Request()

    async def validate(self, token: str) -> dict:
        """
        Validates the token and returns the decoded claims.
        """
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token is missing.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            # Verify the token against Google's certs
            id_info = id_token.verify_oauth2_token(
                id_token=token,
                request=self.request,
                audience=self.audience
            )
            return id_info

        except ValueError as e:
            logger.error(f"OIDC token validation failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            )

# Singleton instance of the validator
oidc_validator = OIDCValidator(audience=config.OIDC_AUDIENCE)

async def verify_oidc_token(request: Request):
    """
    Dependency that can be used on a per-endpoint basis to enforce auth.
    It inspects the Authorization header for a Bearer token.
    """
    if config.REQUIRE_AUTH:
        auth_header: HTTPAuthorizationCredentials = await oidc_scheme(request)
        await oidc_validator.validate(auth_header.credentials)

async def auth_middleware(request: Request, call_next):
    """
    A middleware that enforces OIDC authentication on specific paths.
    Public paths are skipped.
    """
    # List of paths that do not require authentication
    public_paths = [
        "/ping",
        "/health",
        "/docs",
        "/openapi.json",
        "/pronostics",
        "/pronostics/ui",
        "/debug/",
        "/api/pronostics",
    ]

    # If auth is disabled globally, or if the path is public, skip validation
    if not config.REQUIRE_AUTH or request.url.path in public_paths or any(request.url.path.startswith(p) for p in public_paths if p.endswith('/')):
        return await call_next(request)

    try:
        # For protected paths, extract and validate the token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing or invalid.")

        token = auth_header.split(" ")[1]
        await oidc_validator.validate(token)

        return await call_next(request)

    except HTTPException as e:
        # If the token is invalid, return an error response
        logger.warning(f"Auth failed for path {request.url.path}: {e.detail}")
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": e.detail},
            headers=e.headers,
        )
    except Exception as e:
        logger.error(f"Unexpected error in auth middleware: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error during authentication."}
        )
