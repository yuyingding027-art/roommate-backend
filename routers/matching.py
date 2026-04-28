from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import re
import json
from database import get_db, User, UserProfile, MatchScore
from schemas import MatchResult
from auth_utils import get_current_user
from matching_service import (
    compute_habits_score,
    compute_objective_score,
    compute_skills_score,
    compute_personality_score,
    compute_interest_score,
    compute_total_score,
)
import asyncio

router = APIRouter()


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


# ─── 强筛选关键词映射（保留上一版逻辑）────────────────────────────────────────
GENDER_MAP = {
    "女": ["女", "female", "f"], "女性": ["女", "female", "f"], "女生": ["女", "female", "f"],
    "男": ["男", "male", "m"],   "男性": ["男", "male", "m"],   "男生": ["男", "male", "m"],
}
HABIT_MAP = {
    "不抽烟": "no_smoking", "不吸烟": "no_smoking", "不烟": "no_smoking",
    "抽烟": "smoking", "吸烟": "smoking",
    "有猫": "pet", "有狗": "pet", "有宠物": "pet", "养宠物": "pet",
    "不养宠物": "no_pet", "没有宠物": "no_pet",
    "爱干净": "clean_high", "整洁": "clean_high", "干净": "clean_high",
}
SLEEP_MAP = {
    "早睡": "early", "早起": "early",
    "晚睡": "late", "夜猫": "late", "夜猫子": "late", "熬夜": "late",
    "弹性作息": "flexible",
}
SKILL_MAP = {
    "杀虫": "杀虫", "杀虫子": "杀虫", "灭虫": "杀虫",
    "做饭": "做饭", "烹饪": "做饭",
    "开车": "开车", "有车": "开车",
    "修电脑": "修电脑", "调酒": "调酒",
}


def parse_hard_filters(search_query: str) -> dict:
    if not search_query:
        return {}
    filters, remaining = {}, search_query
    for kw, vals in GENDER_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters["gender"] = vals
    for kw, val in SLEEP_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters["sleep_habit"] = val
    for kw, val in HABIT_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters.setdefault("habits_required", [])
            if val not in filters["habits_required"]:
                filters["habits_required"].append(val)
    for kw, val in SKILL_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters.setdefault("skills_required", [])
            if val not in filters["skills_required"]:
                filters["skills_required"].append(val)
    soft = re.sub(r"[，,、。\s]+", " ", remaining).strip()
    if soft:
        filters["soft_query"] = soft
    return filters


def hard_filter_profiles(all_profiles: list, filters: dict) -> list:
    result = []
    for p in all_profiles:
        if "gender" in filters:
            if not p.gender or p.gender.strip().lower() not in [g.lower() for g in filters["gender"]]:
                continue
        if "sleep_habit" in filters:
            if (p.sleep_habit or "").strip() != filters["sleep_habit"]:
                continue
        if "habits_required" in filters:
            ph = set(str_to_list(p.habits or ""))
            if not set(filters["habits_required"]).issubset(ph):
                continue
        if "skills_required" in filters:
            st = (p.special_skills or "").lower()
            if not all(s.lower() in st for s in filters["skills_required"]):
                continue
        result.append(p)
    return result


# ─── 主路由 ─────────────────────────────────────────────────────────────────
@router.get("/", response_model=List[MatchResult])
async def get_matches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    refresh: bool = False,
    search_query: Optional[str] = None,
    priorities: Optional[str] = None,
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    my_profile = result.scalar_one_or_none()
    if not my_profile:
        raise HTTPException(status_code=400, detail="请先完善个人资料")

    all_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id != current_user.id)
    )
    all_profiles = all_result.scalars().all()
    if not all_profiles:
        return []

    # 强筛选
    hard_filters = parse_hard_filters(search_query or "")
    soft_query   = hard_filters.pop("soft_query", None) or search_query
    candidates   = hard_filter_profiles(all_profiles, hard_filters) if hard_filters else all_profiles
    if hard_filters and not candidates:
        return []

    if search_query or priorities:
        refresh = True

    # 缓存命中（无搜索词且无硬筛选时）
    if not refresh and not hard_filters:
        cached = await db.execute(
            select(MatchScore)
            .where(MatchScore.user_id == current_user.id)
            .order_by(MatchScore.total_score.desc())
            .limit(limit)
        )
        cached_scores = cached.scalars().all()
        if len(cached_scores) == len(all_profiles):
            return await _build_match_results(cached_scores, db)

    semaphore = asyncio.Semaphore(10)

    async def score_one(other: UserProfile):
        habits      = compute_habits_score(my_profile, other)
        objective   = compute_objective_score(my_profile, other)
        skills      = compute_skills_score(my_profile, other)
        async with semaphore:
            personality, p_reason = await compute_personality_score(my_profile, other)
            interest,    i_reason = await compute_interest_score(my_profile, other, soft_query)

        total, weights = compute_total_score(habits, objective, skills, personality, interest)

        reason_parts = []
        if i_reason:
            reason_parts.append(i_reason)
        if p_reason:
            reason_parts.append(f"🌟 性格兼容：{p_reason}")
        match_reason = "\n".join(reason_parts) or None

        return (other, habits, objective, skills, personality, interest, total, weights, match_reason)

    tasks   = [score_one(p) for p in candidates]
    results = await asyncio.gather(*tasks)
    valid   = sorted(results, key=lambda x: x[6], reverse=True)[:limit]

    # 写入/更新缓存
    for row in valid:
        other, habits, objective, skills, personality, interest, total, weights, match_reason = row
        existing = await db.execute(
            select(MatchScore).where(
                MatchScore.user_id == current_user.id,
                MatchScore.target_user_id == other.user_id,
            )
        )
        ms = existing.scalar_one_or_none()
        p_score = personality if personality is not None else 50.0
        i_score = interest    if interest    is not None else 50.0
        s_score = skills      if skills      is not None else 0.0

        if ms:
            ms.rule_score        = habits
            ms.ai_score          = i_score
            ms.personality_score = p_score
            ms.total_score       = total
            ms.match_reason      = match_reason
            # 新字段
            if hasattr(ms, "habits_score"):    ms.habits_score    = habits
            if hasattr(ms, "objective_score"): ms.objective_score = objective
            if hasattr(ms, "skills_score"):    ms.skills_score    = s_score
            if hasattr(ms, "interest_score"):  ms.interest_score  = i_score
            if hasattr(ms, "score_weights"):   ms.score_weights   = json.dumps(weights)
        else:
            kwargs = dict(
                user_id          = current_user.id,
                target_user_id   = other.user_id,
                rule_score       = habits,
                ai_score         = i_score,
                personality_score= p_score,
                total_score      = total,
                match_reason     = match_reason,
            )
            if hasattr(MatchScore, "habits_score"):    kwargs["habits_score"]    = habits
            if hasattr(MatchScore, "objective_score"): kwargs["objective_score"] = objective
            if hasattr(MatchScore, "skills_score"):    kwargs["skills_score"]    = s_score
            if hasattr(MatchScore, "interest_score"):  kwargs["interest_score"]  = i_score
            if hasattr(MatchScore, "score_weights"):   kwargs["score_weights"]   = json.dumps(weights)
            db.add(MatchScore(**kwargs))

    await db.commit()

    # 构建返回
    match_results = []
    for row in valid:
        other, habits, objective, skills, personality, interest, total, weights, match_reason = row
        p_score = personality if personality is not None else 50.0
        i_score = interest    if interest    is not None else 50.0
        s_score = skills      if skills      is not None else 0.0
        match_results.append(MatchResult(
            user_id          = other.user_id,
            name             = other.name,
            school           = other.school,
            city             = other.city,
            study_country    = other.study_country,
            study_state      = other.study_state,
            native_language  = other.native_language,
            degree           = other.degree,
            major            = other.major,
            gender           = other.gender,
            zodiac           = other.zodiac,
            mbti             = other.mbti,
            sleep_habit      = other.sleep_habit,
            diet_habit       = other.diet_habit,
            food_preference  = other.food_preference,
            habits           = str_to_list(other.habits or ""),
            budget_currency  = other.budget_currency,
            budget_min       = other.budget_min,
            budget_max       = other.budget_max,
            room_types       = str_to_list(other.room_types or ""),
            roommate_experience = other.roommate_experience,
            special_skills   = str_to_list(other.special_skills or ""),
            bio              = other.bio,
            avatar_url       = other.avatar_url,
            # 旧字段兼容
            rule_score       = round(habits),
            ai_score         = round(i_score),
            personality_score= round(p_score),
            total_score      = round(total),
            # 新字段
            habits_score     = round(habits),
            objective_score  = round(objective),
            skills_score     = round(s_score),
            interest_score   = round(i_score),
            score_weights    = weights,
            match_reason     = match_reason,
        ))
    return match_results


async def _build_match_results(cached_scores, db):
    results = []
    for ms in cached_scores:
        r = await db.execute(
            select(UserProfile).where(UserProfile.user_id == ms.target_user_id)
        )
        profile = r.scalar_one_or_none()
        if not profile:
            continue

        weights = {}
        if hasattr(ms, "score_weights") and ms.score_weights:
            try: weights = json.loads(ms.score_weights)
            except Exception: weights = {}

        h_score = getattr(ms, "habits_score",    ms.rule_score)
        o_score = getattr(ms, "objective_score", 0.0)
        s_score = getattr(ms, "skills_score",    0.0)
        i_score = getattr(ms, "interest_score",  ms.ai_score)

        results.append(MatchResult(
            user_id          = profile.user_id,
            name             = profile.name,
            school           = profile.school,
            city             = profile.city,
            study_country    = profile.study_country,
            study_state      = profile.study_state,
            native_language  = profile.native_language,
            degree           = profile.degree,
            major            = profile.major,
            gender           = profile.gender,
            zodiac           = profile.zodiac,
            mbti             = profile.mbti,
            sleep_habit      = profile.sleep_habit,
            diet_habit       = profile.diet_habit,
            food_preference  = profile.food_preference,
            habits           = str_to_list(profile.habits or ""),
            budget_currency  = profile.budget_currency,
            budget_min       = profile.budget_min,
            budget_max       = profile.budget_max,
            room_types       = str_to_list(profile.room_types or ""),
            roommate_experience = profile.roommate_experience,
            special_skills   = str_to_list(profile.special_skills or ""),
            bio              = profile.bio,
            avatar_url       = profile.avatar_url,
            rule_score       = round(ms.rule_score),
            ai_score         = round(ms.ai_score),
            personality_score= round(ms.personality_score),
            total_score      = round(ms.total_score),
            habits_score     = round(h_score),
            objective_score  = round(o_score),
            skills_score     = round(s_score),
            interest_score   = round(i_score),
            score_weights    = weights or None,
            match_reason     = ms.match_reason,
        ))
    return results
