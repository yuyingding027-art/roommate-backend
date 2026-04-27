from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, User, EmailVerification
from schemas import RegisterRequest, LoginResponse, SendCodeRequest, VerifyCodeRequest
from auth_utils import hash_password, verify_password, create_access_token
import resend
import os
import random
import string
from datetime import datetime, timedelta

router = APIRouter()

resend.api_key = os.getenv("RESEND_API_KEY")

ALLOWED_DOMAINS = [".edu", ".ac.", ".hku.hk"]

def is_edu_email(email: str) -> bool:
    email_lower = email.lower()
    return any(d in email_lower for d in ALLOWED_DOMAINS)

def generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


@router.post("/send-code")
async def send_verification_code(body: SendCodeRequest, db: AsyncSession = Depends(get_db)):
    if not is_edu_email(body.email):
        raise HTTPException(status_code=400, detail="仅支持教育机构邮箱（.edu / .ac / .hku）")

    # 检查是否已注册
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 生成验证码，5分钟有效
    code = generate_code()
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    # 存入数据库（覆盖旧的）
    existing = await db.execute(
        select(EmailVerification).where(EmailVerification.email == body.email)
    )
    ev = existing.scalar_one_or_none()
    if ev:
        ev.code = code
        ev.expires_at = expires_at
    else:
        ev = EmailVerification(email=body.email, code=code, expires_at=expires_at)
        db.add(ev)
    await db.commit()

    # 发送邮件
    try:
        resend.Emails.send({
            "from": "UniRoomi <onboarding@resend.dev>",  # 改成你的域名
            "to": body.email,
            "subject": "UniRoomi 验证码",
            "html": f"""
                <h2>欢迎加入 UniRoomi 觅舍！</h2>
                <p>你的验证码是：</p>
                <h1 style="letter-spacing:8px; color:#4F46E5;">{code}</h1>
                <p>验证码5分钟内有效，请勿泄露给他人。</p>
            """
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail="验证码发送失败，请稍后重试")

    return {"message": "验证码已发送，请查收邮件"}


@router.post("/register", response_model=LoginResponse)
async def register(body: VerifyCodeRequest, db: AsyncSession = Depends(get_db)):
    if not is_edu_email(body.email):
        raise HTTPException(status_code=400, detail="仅支持教育机构邮箱（.edu / .ac / .hku）")

    # 验证码校验
    result = await db.execute(
        select(EmailVerification).where(EmailVerification.email == body.email)
    )
    ev = result.scalar_one_or_none()
    if not ev or ev.code != body.code:
        raise HTTPException(status_code=400, detail="验证码错误")
    if ev.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")

    # 检查是否已注册
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 创建用户
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
