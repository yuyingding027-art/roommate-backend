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

def profile_to_dict(profile: UserProfile, email: str = None) -> dict:
    d = {c.name: getattr(profile, c.name) for c in profile.__table__.columns}
    d["special_skills"] = str_to_list(d.get("special_skills") or "")
    d["habits"]         = str_to_list(d.get("habits") or "")
    d["room_types"]     = str_to_list(d.get("room_types") or "")
    d["email"]          = email
    return d


@router.post("/profile", response_model=ProfileResponse)
async def create_or_update_profile(
    body: ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    data = body.model_dump()
    data["special_skills"] = list_to_str(data.get("special_skills") or [])
    data["habits"]         = list_to_str(data.get("habits") or [])
    data["room_types"]     = list_to_str(data.get("room_types") or [])

    if profile:
        # profile version+1
        current_version = getattr(profile, "profile_version", 1) or 1
        data["profile_version"] = current_version + 1
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        data["profile_version"] = 1
        profile = UserProfile(user_id=current_user.id, **data)
        db.add(profile)

    await db.commit()
    await db.refresh(profile)
    return profile_to_dict(profile, email=current_user.email)


@router.get("/profile/me", response_model=ProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_to_dict(profile, email=current_user.email)


@router.get("/profile/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    user_result = await db.execute(select(User).where(User.id == profile.user_id))
    user = user_result.scalar_one_or_none()
    return profile_to_dict(profile, email=user.email if user else None)


# ── revoke/recover profile ──────────────────────────────────────────────────────
@router.post("/profile/searchable")
async def toggle_searchable(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    切换当前用户的档案可查询状态。toggle the current user's profile searchability
    撤销：is_searchable=False，匹配搜索中不再出现 revoke, no show in matching page
    恢复：is_searchable=True，重新出现在搜索中 recover, showcases in matching page
    返回新状态。
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="请先完善个人资料")

    current_state = getattr(profile, "is_searchable", True)
    profile.is_searchable = not current_state
    await db.commit()

    return {
        "is_searchable": profile.is_searchable,
        "message": "档案已恢复，可以被其他用户搜索到" if profile.is_searchable else "档案已撤销，其他用户将无法在匹配中看到你",
    }
