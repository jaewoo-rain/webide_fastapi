import os
from typing import Optional
from datetime import datetime, timezone

import jwt # pip install PyJWT==2.8.0
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from config import ALGORITHM, JWT_SECRET


class AuthUser(BaseModel):
    username: str
    role: str
    category: str
    exp: int

# 토큰 읽어오기
def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    return auth[7:]

def verify_and_parse_jwt(token: str) -> AuthUser:

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        # 스프링의 응답 헤더 스타일을 맞추고 싶다면 아래처럼 커스텀 헤더 추가 가능
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"Access-Token-Expired": "true"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"Invalid-Access-Token": "true"},
        )

    # category 확인 (스프링과 동일한 정책)
    category = payload.get("category")
    if category != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not an access token",
            headers={"Invalid-Access-Token": "true"},
        )

    # exp(UTC) 수동 체크(선택적: PyJWT가 이미 검사했지만 clock skew 조정용)
    exp = payload.get("exp")
    if exp is None or datetime.fromtimestamp(exp, tz=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"Access-Token-Expired": "true"},
        )

    username = payload.get("username")
    role = payload.get("role")
    if not username or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing claims",
        )

    return AuthUser(username=username, role=role, category=category, exp=exp)

# FastAPI dependency
async def get_current_user(request: Request) -> AuthUser:
    token = _extract_bearer_token(request)
    return verify_and_parse_jwt(token)
