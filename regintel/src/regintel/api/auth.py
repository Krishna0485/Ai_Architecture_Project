"""API-key authentication -> SecurityContext. Tenant and groups come only from the key grant."""

from __future__ import annotations

import hmac

from regintel.config import ApiKeyGrant
from regintel.retrieval.base import SecurityContext


def resolve_api_key(
    api_key: str | None, grants: dict[str, ApiKeyGrant], request_id: str = ""
) -> SecurityContext | None:
    if not api_key:
        return None
    for key, grant in grants.items():
        # Constant-time comparison over every key to avoid timing side channels.
        if hmac.compare_digest(key.encode("utf-8"), api_key.encode("utf-8")):
            return SecurityContext(grant.tenant_id, tuple(grant.groups), grant.actor, request_id)
    return None
