"""Firebase authentication and claim-to-principal translation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Principal:
    uid: str
    roles: frozenset[str]
    node_ids: frozenset[str]
    claims: Mapping[str, Any]

    def has_permission(self, permission: str) -> bool:
        return "*" in permissions_for_roles(self.roles) or permission in permissions_for_roles(
            self.roles
        )

    def can_access_node(self, node_id: str) -> bool:
        return "admin" in self.roles or "*" in self.node_ids or node_id in self.node_ids


ROLE_PERMISSIONS = {
    "viewer": frozenset(),
    "operator": frozenset({"vehicle:write"}),
    "admin": frozenset({"*"}),
}


def permissions_for_roles(roles: frozenset[str]) -> frozenset[str]:
    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(permissions)


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    if not uid:
        raise ValueError("verified token is missing uid")
    claimed_roles = claims.get("roles", claims.get("role", ()))
    if isinstance(claimed_roles, str):
        roles = {claimed_roles}
    elif isinstance(claimed_roles, (list, tuple, set)):
        roles = {str(role) for role in claimed_roles}
    else:
        roles = set()
    if claims.get("admin") is True:
        roles.add("admin")
    roles &= set(ROLE_PERMISSIONS)
    if not roles:
        roles.add("viewer")
    claimed_nodes = claims.get("node_ids", ())
    if isinstance(claimed_nodes, str):
        node_ids = {claimed_nodes}
    elif isinstance(claimed_nodes, (list, tuple, set)):
        node_ids = {str(node_id) for node_id in claimed_nodes}
    else:
        node_ids = set()
    return Principal(
        uid=uid,
        roles=frozenset(roles),
        node_ids=frozenset(node_ids),
        claims=dict(claims),
    )


@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> Principal: ...


class FirebaseTokenVerifier:
    """Uses the Admin SDK, including revocation/disabled-user checks."""

    def __init__(self, project_id: str) -> None:
        if not project_id.strip():
            raise ValueError("Firebase project_id must not be empty")
        import firebase_admin

        app_name = f"aivd-{project_id}"
        try:
            self._app = firebase_admin.get_app(app_name)
        except ValueError:
            self._app = firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=app_name,
            )

    def verify(self, token: str) -> Principal:
        if not token.strip():
            raise ValueError("token must not be empty")
        from firebase_admin import auth

        claims = auth.verify_id_token(
            token,
            app=self._app,
            check_revoked=True,
        )
        return principal_from_claims(claims)
