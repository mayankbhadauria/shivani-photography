import os
import json
import urllib.request
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

COGNITO_REGION = os.getenv("COGNITO_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "")

JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"

security = HTTPBearer()


@lru_cache(maxsize=1)
def get_jwks():
    with urllib.request.urlopen(JWKS_URL, timeout=10) as resp:
        return json.loads(resp.read().decode())


def decode_token(token: str) -> dict:
    try:
        jwks = get_jwks()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
        if key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=COGNITO_APP_CLIENT_ID,
            options={"verify_exp": True},
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}")


def get_user_groups(payload: dict) -> list[str]:
    return payload.get("cognito:groups", [])


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    return decode_token(credentials.credentials)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if "Admin" not in get_user_groups(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def require_downloader_or_admin(user: dict = Depends(get_current_user)) -> dict:
    groups = get_user_groups(user)
    if not any(g in groups for g in ["Admin", "Downloader"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Downloader or Admin role required")
    return user


def require_any_authenticated(user: dict = Depends(get_current_user)) -> dict:
    return user
