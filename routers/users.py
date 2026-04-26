from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, User, UserProfile
from schemas import ProfileCreate, ProfileResponse
from auth_utils import get_current_user

router = APIRouter()

def skills_to_str(skills: list) -> str:
    return ",".join(skills) if skills else ""

def str_to_skills(s: str) -> list:
    return s.split(",") if s else []

@router.post("/profile", response_model=ProfileResponse)
async def create_or_update_profile(
    body: ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    data = body.model_dump()
    data["special_skills"] = skills_to_str(data.get("special_skills") or [])

    if profile:
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        profile = UserProfile(user_id=current_user.id, **data)
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    resp = ProfileResponse.model_validate(profile)
    resp.special_skills = str_to_skills(profile.special_skills or "")
    return resp

@router.get("/profile/me", response_model=ProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="请先完善个人资料")
    resp = ProfileResponse.model_validate(profile)
    resp.special_skills = str_to_skills(profile.special_skills or "")
    return resp

@router.get("/profile/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    resp = ProfileResponse.model_validate(profile)
    resp.special_skills = str_to_skills(profile.special_skills or "")
    return resp
