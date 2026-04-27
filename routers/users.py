from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, User, UserProfile
from schemas import ProfileCreate, ProfileResponse
from auth_utils import get_current_user

router = APIRouter()

def list_to_str(lst: list) -> str:
    return ",".join(lst) if lst else ""

def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []

def profile_to_dict(profile: UserProfile) -> dict:
    d = {c.name: getattr(profile, c.name) for c in profile.__table__.columns}
    d["special_skills"] = str_to_list(d.get("special_skills") or "")
    d["habits"] = str_to_list(d.get("habits") or "")
    d["room_types"] = str_to_list(d.get("room_types") or "")
    return d

@router.post("/profile", response_model=ProfileResponse)
async def create_or_update_profile(
    body: ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    data = body.model_dump()
    data["special_skills"] = list_to_str(data.get("special_skills") or [])
    data["habits"] = list_to_str(data.get("habits") or [])
    data["room_types"] = list_to_str(data.get("room_types") or [])

    if profile:
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        profile = UserProfile(user_id=current_user.id, **data)
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    return profile_to_dict(profile)


@router.get("/profile/me", response_model=ProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    return profile_to_dict(profile)


@router.get("/profile/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile_to_dict(profile)
