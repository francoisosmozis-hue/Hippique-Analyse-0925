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

# Singleton instance of the validator - initialized only if needed
oidc_validator: OIDCValidator | None = None
if config.REQUIRE_AUTH:
    try:
        oidc_validator = OIDCValidator(audience=config.OIDC_AUDIENCE)
    except ValueError as e:
        logger.error(f"Failed to initialize OIDCValidator: {e}", exc_info=True)
        # Depending on strictness, you might want to exit here if auth is required but misconfigured
        # For now, we log the error, and it will fail at runtime if an auth-protected route is hit.
        pass

async def verify_oidc_token(request: Request):
    """
    Dependency that can be used on a per-endpoint basis to enforce auth.
    It inspects the Authorization header for a Bearer token.
    """
    if config.REQUIRE_AUTH:
        if not oidc_validator:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OIDC Validator is not configured.")
        auth_header: HTTPAuthorizationCredentials = await oidc_scheme(request)
        if auth_header:
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
        # Allow accessing pronostics data without auth
        "/api/pronostics",
        # Allow task handlers to be called without auth
        "/tasks/run-phase",
        "/receive-trigger",
        # Keep debug endpoints accessible, especially for local/staging
        "/debug/",
    ]
    
    # FastAPI's router registers UI paths like /api/pronostics/ui, not needed to list twice
    # Static files are also typically handled separately and don't need to be in this list.

    # If auth is disabled globally, or if the path is public, skip validation
    path = request.url.path
    if not config.REQUIRE_AUTH or any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    try:
        if not oidc_validator:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OIDC Validator is not configured.")
            
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
