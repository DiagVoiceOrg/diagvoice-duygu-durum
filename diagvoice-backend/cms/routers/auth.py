from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from cms.auth_utils import create_access_token, verify_password
from cms.database import get_db
from cms.deps import require_user
from cms.schemas import LoginRequest, TokenResponse, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    db = get_db()
    user = await db.users.find_one({"email": body.email.lower().strip()})
    if not user or not verify_password(body.password, user.get("passwordHash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(sub=user["email"], role=user.get("role", "admin"))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserMe)
async def me(payload: Annotated[dict, Depends(require_user)]):
    return UserMe(email=payload["sub"], role=payload.get("role", "admin"))
