"""
Operator tokens for the endpoints that change what the system believes.

    python -m app.security new-token     # prints a token and its hash

WHAT IS PROTECTED
  - saving a supply plan as a record         (it becomes part of the audit trail)
  - recording an override against one         (it is operator testimony)
  - submitting a field report, in production  (it closes and slows roads in
    routing) unless PUBLIC_FIELD_REPORTS=true

Reading, forecasting and planning without saving stay public: they change
nothing, and planning is bounded and concurrency-limited.

HOW
A token is a random 32-byte secret sent as `Authorization: Bearer <token>`.
The server holds only SHA-256 digests (OPERATOR_TOKEN_HASHES), so a leaked
environment dump does not leak usable tokens, and comparison is constant-time.
Several hashes can be configured, so one operator's token can be revoked by
removing its hash without affecting anyone else.

This is deliberately small. It is not user accounts: tokens identify "an
authorised operator", not a person, which matches the no-personal-data stance
of field reports (0005). Real multi-user auth (SSO, roles) belongs in front of
the deployment when an agency adopts it.

IN DEVELOPMENT
With no hashes configured and ENVIRONMENT != production, writes are open so
the local stack works without setup. Configuring any hash enforces tokens in
every environment, which is how the test suite checks enforcement.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sys

from fastapi import Header, HTTPException

from app.config import get_settings


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _presented_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def is_authorised(authorization: str | None) -> bool:
    settings = get_settings()
    hashes = [h.lower() for h in settings.operator_token_hashes]
    if not hashes:
        # Only reachable outside production: startup refuses production
        # without hashes (see main.py).
        return not settings.is_production
    token = _presented_token(authorization)
    if token is None:
        return False
    digest = token_hash(token)
    # Compare against every hash without short-circuiting, so timing does not
    # reveal how many hashes are configured or which one nearly matched.
    matched = False
    for h in hashes:
        matched |= hmac.compare_digest(digest, h)
    return matched


def require_operator(authorization: str | None = Header(default=None)) -> None:
    if not is_authorised(authorization):
        raise HTTPException(
            status_code=401,
            detail="This action needs an operator token (Authorization: Bearer <token>).",
            headers={"WWW-Authenticate": "Bearer"},
        )


def field_reports_open() -> bool:
    settings = get_settings()
    return settings.public_field_reports or (
        not settings.operator_token_hashes and not settings.is_production
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] != ["new-token"]:
        print("usage: python -m app.security new-token")
        return 2
    token = secrets.token_urlsafe(32)
    print("token (give to the operator; not stored anywhere):")
    print(f"  {token}")
    print("hash (add to OPERATOR_TOKEN_HASHES on the API):")
    print(f"  {token_hash(token)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
