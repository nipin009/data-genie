"""Small, deployment-friendly API-key RBAC boundary."""
import hmac
from typing import Optional

from fastapi import HTTPException, Request, status

from .config import get_settings


def role_for_key(candidate: Optional[str]) -> Optional[str]:
    """Return an authorized role for a configured key, without timing leaks."""
    if not candidate:
        return None
    for item in get_settings().API_KEYS.split(","):
        key, sep, role = item.strip().partition(":")
        if sep and key and role and hmac.compare_digest(candidate, key):
            return role.strip().lower()
    return None


async def require_role(request: Request, *allowed_roles: str) -> str:
    """Apply optional authentication and role authorization."""
    if not get_settings().AUTH_ENABLED:
        return "local"
    role = role_for_key(request.headers.get("X-API-Key"))
    if not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="A valid X-API-Key is required.",
                            headers={"WWW-Authenticate": "ApiKey"})
    if allowed_roles and role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your role is not allowed to access this resource.")
    return role
