from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, User
from schemas import RegisterRequest, LoginResponse
from auth_utils import hash_password, verify_password, create_access_token

router = APIRouter()

ALLOWED_DOMAINS = [".edu", ".ac.", ".hku.hk"]

def is_edu_email(email: str) -> bool:
    email_lower = email.lower()
    return any(d in email_lower for d in ALLOWED_DOMAINS)


@router.post("/register", response_model=LoginResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not is_edu_email(body.email):
        raise HTTPException(status_code=400, detail="仅支持教育机构邮箱（.edu / .ac / .hku）")

    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id))
    return LoginResponse(access_token=token, user_id=str(user.id))


@router.post("/login", response_model=LoginResponse)
async def login(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    token = create_access_token(str(user.id))
    return LoginResponse(access_token=token, user_id=str(user.id))
