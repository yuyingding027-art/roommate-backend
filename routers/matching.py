from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from database import get_db, User, UserProfile, MatchScore
from schemas import MatchResult
from auth_utils import get_current_user
from matching_service import (
    compute_rule_score, compute_ai_score,
    compute_personality_score, compute_total_score
)
import asyncio

router = APIRouter()

def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


@router.get("/", response_model=List[MatchResult])
async def get_matches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    refresh: bool = False,
    search_query: Optional[str] = None,
    priorities: Optional[str] = None
):
    priorities_list = [p.strip() for p in priorities.split(",")] if priorities else None

    result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    my_profile = result.scalar_one_or_none()
    if not my_profile:
        raise HTTPException(status_code=400, detail="请先完善个人资料")

    all_profiles_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id != current_user.id)
    )
    all_profiles = all_profiles_result.scalars().all()

    if not all_profiles:
        return []

    # 有搜索词或优先级时强制刷新
    if search_query or priorities:
        refresh = True

    if not refresh:
        cached = await db.execute(
            select(MatchScore).where(MatchScore.user_id == current_user.id)
            .order_by(MatchScore.total_score.desc())
            .limit(limit)
        )
        cached_scores = cached.scalars().all()
        if len(cached_scores) == len(all_profiles):
            return await _build_match_results(cached_scores, db)

    semaphore = asyncio.Semaphore(10)

    async def score_one(other: UserProfile):
        rule = compute_rule_score(my_profile, other, priorities_list)
        async with semaphore:
            ai, ai_reason = await compute_ai_score(my_profile, other, search_query, priorities_list)
            personality, p_reason = await compute_personality_score(my_profile, other)
        total = compute_total_score(rule, ai, personality, priorities_list)
        reason_parts = []
        if ai_reason:
            reason_parts.append(ai_reason)
        if p_reason:
            reason_parts.append(f"💡 性格兼容：{p_reason}")
        match_reason = "\n".join(reason_parts) if reason_parts else None
        return (other, rule, ai, personality, total, match_reason)

    tasks = [score_one(p) for p in all_profiles]
    results = await asyncio.gather(*tasks)
    valid = [r for r in results if r is not None]
    valid.sort(key=lambda x: x[4], reverse=True)
    valid = valid[:limit]

    for other, rule, ai, personality, total, match_reason in valid:
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
            ms.match_reason = match_reason
        else:
            ms = MatchScore(
                user_id=current_user.id,
                target_user_id=other.user_id,
                rule_score=rule,
                ai_score=ai,
                personality_score=personality,
                total_score=total,
                match_reason=match_reason
            )
            db.add(ms)

    await db.commit()

    match_results = []
    for other, rule, ai, personality, total, match_reason in valid:
        match_results.append(MatchResult(
            user_id=other.user_id,
            name=other.name,
            school=other.school,
            city=other.city,
            study_country=other.study_country,
            study_state=other.study_state,
            native_language=other.native_language,
            degree=other.degree,
            major=other.major,
            gender=other.gender,
            zodiac=other.zodiac,
            mbti=other.mbti,
            sleep_habit=other.sleep_habit,
            diet_habit=other.diet_habit,
            food_preference=other.food_preference,
            habits=str_to_list(other.habits or ""),
            budget_currency=other.budget_currency,
            budget_min=other.budget_min,
            budget_max=other.budget_max,
            room_types=str_to_list(other.room_types or ""),
            roommate_experience=other.roommate_experience,
            special_skills=str_to_list(other.special_skills or ""),
            bio=other.bio,
            avatar_url=other.avatar_url,
            rule_score=round(rule),
            ai_score=round(ai),
            personality_score=round(personality),
            total_score=round(total),
            match_reason=match_reason,
        ))
    return match_results


async def _build_match_results(cached_scores, db):
    results = []
    for ms in cached_scores:
        r = await db.execute(select(UserProfile).where(UserProfile.user_id == ms.target_user_id))
        profile = r.scalar_one_or_none()
        if not profile:
            continue
        results.append(MatchResult(
            user_id=profile.user_id,
            name=profile.name,
            school=profile.school,
            city=profile.city,
            study_country=profile.study_country,
            study_state=profile.study_state,
            native_language=profile.native_language,
            degree=profile.degree,
            major=profile.major,
            gender=profile.gender,
            zodiac=profile.zodiac,
            mbti=profile.mbti,
            sleep_habit=profile.sleep_habit,
            diet_habit=profile.diet_habit,
            food_preference=profile.food_preference,
            habits=str_to_list(profile.habits or ""),
            budget_currency=profile.budget_currency,
            budget_min=profile.budget_min,
            budget_max=profile.budget_max,
            room_types=str_to_list(profile.room_types or ""),
            roommate_experience=profile.roommate_experience,
            special_skills=str_to_list(profile.special_skills or ""),
            bio=profile.bio,
            avatar_url=profile.avatar_url,
            rule_score=round(ms.rule_score),
            ai_score=round(ms.ai_score),
            personality_score=round(ms.personality_score),
            total_score=round(ms.total_score),
            match_reason=ms.match_reason,
        ))
    return results
