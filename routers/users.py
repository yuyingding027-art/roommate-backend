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
#revised
@router.post("/profile", response_model=ProfileResponse)
async def create_or_update_profile(
    body: ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()

    data = body.model_dump()
    # 存储时转为字符串
    data["special_skills"] = skills_to_str(data.get("special_skills") or [])

    if profile:
        for k, v in data.items():
            setattr(profile, k, v)
    else:
        profile = UserProfile(user_id=current_user.id, **data)
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    # --- 关键修改点开始 ---
    
    # 1. 先把 profile 里的数据转成字典，方便修改
    profile_dict = {column.name: getattr(profile, column.name) for column in profile.__table__.columns}
    
    # 2. 将数据库里的字符串转回列表，确保符合 ProfileResponse 的要求
    profile_dict["special_skills"] = str_to_skills(profile.special_skills or "")
    
    # 3. 使用校验过的字典返回，或者直接返回字典（FastAPI 会自动根据 response_model 校验）
    return profile_dict

    # --- 关键修改点结束 ---

@router.get("/profile/me", response_model=ProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # --- 核心修复代码开始 ---
    # 1. 先把 SQLAlchemy 对象转成字典
    profile_data = {c.name: getattr(profile, c.name) for c in profile.__table__.columns}
    
    # 2. 手动转换技能字段：如果是字符串，就用逗号切开；如果是空，就给空数组
    raw_skills = profile_data.get("special_skills") or ""
    profile_data["special_skills"] = raw_skills.split(",") if raw_skills else []
    # --- 核心修复代码结束 ---

    return profile_data
    
@router.get("/profile/{user_id}", response_model=ProfileResponse)
async def get_user_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    resp = ProfileResponse.model_validate(profile)
    resp.special_skills = str_to_skills(profile.special_skills or "")
    return resp
