from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from database import get_db, User, UserProfile, MatchScore
from schemas import MatchResult
from auth_utils import get_current_user
from matching_service import (
    compute_rule_score, compute_ai_score,
    compute_personality_score, compute_total_score
)
import asyncio

router = APIRouter()

def str_to_skills(s: str) -> list:
    return s.split(",") if s else []

@router.get("/", response_model=List[MatchResult])
async def get_matches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    refresh: bool = False
):
    # 获取当前用户profile
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    my_profile = result.scalar_one_or_none()
    if not my_profile:
        raise HTTPException(status_code=400, detail="请先完善个人资料")

    # 如果不强制刷新，先查缓存
    if not refresh:
        cached = await db.execute(
            select(MatchScore).where(MatchScore.user_id == current_user.id)
            .order_by(MatchScore.total_score.desc())
            .limit(limit)
        )
        cached_scores = cached.scalars().all()
        if cached_scores:
            return await _build_match_results(cached_scores, db)

    # 获取所有其他用户profile
    all_profiles_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id != current_user.id)
    )
    all_profiles = all_profiles_result.scalars().all()

    # 并发计算AI分（最多同时10个）
    semaphore = asyncio.Semaphore(10)

    async def score_one(other: UserProfile):
        rule = compute_rule_score(my_profile, other)
        if rule == 0:  # 不同校/城直接跳过
            return None
        async with semaphore:
            ai = await compute_ai_score(my_profile, other)
        personality = compute_personality_score(my_profile, other)
        total = compute_total_score(rule, ai, personality)
        return (other, rule, ai, personality, total)

    tasks = [score_one(p) for p in all_profiles]
    results = await asyncio.gather(*tasks)
    valid = [r for r in results if r is not None]
    valid.sort(key=lambda x: x[4], reverse=True)
    valid = valid[:limit]

    # 写入/更新缓存
    for other, rule, ai, personality, total in valid:
        existing = await db.execute(
            select(MatchScore).where(
                MatchScore.user_id == current_user.id,
                MatchScore.target_user_id == other.user_id
            )
        )
        ms = existing.scalar_one_or_none()
        if ms:
            ms.rule_score = rule
            ms.ai_score = ai
            ms.personality_score = personality
            ms.total_score = total
        else:
            ms = MatchScore(
                user_id=current_user.id,
                target_user_id=other.user_id,
                rule_score=rule,
                ai_score=ai,
                personality_score=personality,
                total_score=total
            )
            db.add(ms)

    await db.commit()

    # 返回结果
    match_results = []
    for other, rule, ai, personality, total in valid:
        match_results.append(MatchResult(
            user_id=other.user_id,
            name=other.name,
            school=other.school,
            city=other.city,
            gender=other.gender,
            zodiac=other.zodiac,
            mbti=other.mbti,
            sleep_habit=other.sleep_habit,
            diet_habit=other.diet_habit,
            food_preference=other.food_preference,
            budget_min=other.budget_min,
            budget_max=other.budget_max,
            roommate_experience=other.roommate_experience,
            special_skills=str_to_skills(other.special_skills or ""),
            bio=other.bio,
            avatar_url=other.avatar_url,
            rule_score=round(rule, 1),
            ai_score=round(ai, 1),
            personality_score=round(personality, 1),
            total_score=round(total, 1),
        ))
    return match_results

async def _build_match_results(cached_scores, db):
    results = []
    for ms in cached_scores:
        r = await db.execute(select(UserProfile).where(UserProfile.user_id == ms.target_user_id))
        profile = r.scalar_one_or_none()
        if not profile:
            continue
        
        # 使用统一的 str_to_skills 处理逻辑
        skills_list = str_to_skills(profile.special_skills or "")
        
        results.append(MatchResult(
            user_id=profile.user_id,
            name=profile.name,
            school=profile.school,
            city=profile.city,
            gender=profile.gender,
            zodiac=profile.zodiac,
            mbti=profile.mbti,
            sleep_habit=profile.sleep_habit,
            diet_habit=profile.diet_habit,
            food_preference=profile.food_preference,
            budget_min=profile.budget_min,
            budget_max=profile.budget_max,
            roommate_experience=profile.roommate_experience,
            special_skills=skills_list,  # 确保这里是 list
            bio=profile.bio,
            avatar_url=profile.avatar_url,
            rule_score=round(ms.rule_score, 1),
            ai_score=round(ms.ai_score, 1),
            personality_score=round(ms.personality_score, 1),
            total_score=round(ms.total_score, 1),
        ))
    return results
