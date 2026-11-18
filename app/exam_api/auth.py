"""Verifies Cognito ID tokens and exposes the caller's identity and role."""
import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException


@dataclass
class User:
    sub: str
    email: str
    groups: list[str]


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    region = os.environ["AWS_REGION"]
    pool = os.environ["COGNITO_POOL_ID"]
    return jwt.PyJWKClient(f"https://cognito-idp.{region}.amazonaws.com/{pool}/.well-known/jwks.json")


def current_user(authorization: str = Header(default="")) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")
    token = authorization.removeprefix("Bearer ")
    region = os.environ["AWS_REGION"]
    pool = os.environ["COGNITO_POOL_ID"]
    try:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=os.environ["COGNITO_CLIENT_ID"],
            issuer=f"https://cognito-idp.{region}.amazonaws.com/{pool}",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc
    if claims.get("token_use") != "id":
        raise HTTPException(401, "ID token required")
    return User(sub=claims["sub"], email=claims.get("email", ""), groups=claims.get("cognito:groups", []))


def require(user: User, role: str) -> None:
    if role not in user.groups and "admin" not in user.groups:
        raise HTTPException(403, f"Only {role}s can do this")
