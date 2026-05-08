from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import json
from database import get_db, User, UserProfile, MatchScore
from schemas import MatchResult
from auth_utils import get_current_user
from matching_service import (
    compute_objective_score,
    compute_habits_score,
    compute_personality_score,
    compute_skills_label,
    compute_total_score,
)
import asyncio

router = APIRouter()


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


# ─── 严格筛选（搜索框上方填空）───────────────────────────────────────────────
import re

# ─── 搜索词 → 硬筛选关键词映射 ───────────────────────────────────────────────
DIET_MAP = {
    "一起吃":   "together", "一起":     "together", "一块吃":   "together",
    "各自":     "separate", "各自解决": "separate", "分开吃":   "separate",
    "不一起":   "separate", "不一块":   "separate",
    "外卖":     "takeout",  "点外卖":   "takeout",
    "弹性饮食": "flexible", "饮食弹性": "flexible",
}
HABIT_MAP = {
    "不抽烟": "no_smoking", "不吸烟": "no_smoking", "不烟": "no_smoking",
    "抽烟":   "smoking",    "吸烟":   "smoking",
    "有猫":   "pet",        "有狗":   "pet",   "有宠物": "pet",  "养宠物": "pet",
    "不养宠物": "no_pet",   "没有宠物": "no_pet",
    "爱干净": "clean_high", "整洁":   "clean_high", "干净": "clean_high",
}
SLEEP_MAP = {
    "早睡": "early", "早起": "early",
    "晚睡": "late",  "夜猫": "late",  "夜猫子": "late", "熬夜": "late",
    "弹性作息": "flexible",
}
SKILL_MAP = {
    "杀虫":   "杀虫", "杀虫子": "杀虫", "灭虫":  "杀虫",
    "做饭":   "做饭", "烹饪":   "做饭",
    "开车":   "开车", "有车":   "开车",
    "修电脑": "修电脑", "调酒":  "调酒",
}
GENDER_MAP = {
    "女": ["女", "female", "f"], "女性": ["女", "female", "f"], "女生": ["女", "female", "f"],
    "男": ["男", "male",   "m"], "男性": ["男", "male",   "m"], "男生": ["男", "male",   "m"],
}


def parse_search_query(search_query: str) -> dict:
    """
    从自然语言搜索词解析硬筛选条件。
    返回 filters dict，无法结构化的剩余词放入 soft_query 传给 AI。
    """
    if not search_query:
        return {}
    filters = {}
    remaining = search_query

    for kw, vals in GENDER_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters["gender"] = vals

    for kw, val in SLEEP_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters["sleep_habit"] = val

    for kw, val in DIET_MAP.items():
        if kw in remaining:
            remaining = remaining.replace(kw, "")
            filters["diet_habit"] = val

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


def filter_by_search(all_profiles: list, filters: dict) -> list:
    """
    根据 parse_search_query 解析出的条件严格过滤，AND 逻辑。
    """
    if not filters:
        return all_profiles
    result = []
    for p in all_profiles:
        if "gender" in filters:
            if not p.gender or p.gender.strip().lower() not in [g.lower() for g in filters["gender"]]:
                continue
        if "sleep_habit" in filters:
            if (p.sleep_habit or "").strip() != filters["sleep_habit"]:
                continue
        if "diet_habit" in filters:
            if (p.diet_habit or "").strip() != filters["diet_habit"]:
                continue
        if "habits_required" in filters:
            ph = set((p.habits or "").split(","))
            if not set(filters["habits_required"]).issubset(ph):
                continue
        if "skills_required" in filters:
            st = (p.special_skills or "").lower()
            if not all(s.lower() in st for s in filters["skills_required"]):
                continue
        result.append(p)
    return result


def hard_filter_profiles(
    all_profiles: list,
    study_country: Optional[str] = None,
    school:        Optional[str] = None,
    study_state:   Optional[str] = None,
    gender:        Optional[str] = None,
    language:      Optional[str] = None,
) -> list:
    """
    所有传入的非空字段都必须严格匹配（AND逻辑）。
    空字段不筛选。
    """
    result = []
    for p in all_profiles:
        if study_country:
            if not p.study_country:
                continue
            if p.study_country.strip().lower() != study_country.strip().lower():
                continue
        if school:
            if not p.school:
                continue
            if school.strip().lower() not in p.school.strip().lower():
                continue
        if study_state:
            if not p.study_state:
                continue
            if p.study_state.strip().lower() != study_state.strip().lower():
                continue
        if gender:
            if not p.gender:
                continue
            # 支持中英文匹配
            gender_map = {
                "女": ["女", "female", "f"],
                "男": ["男", "male", "m"],
                "female": ["女", "female", "f"],
                "male": ["男", "male", "m"],
            }
            allowed = gender_map.get(gender.lower(), [gender.lower()])
            if p.gender.strip().lower() not in [g.lower() for g in allowed]:
                continue
        if language:
            if not p.native_language:
                continue
            if p.native_language.strip().lower() != language.strip().lower():
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
    # ── 严格筛选参数（对应搜索框上方填空）──
    filter_study_country: Optional[str] = None,
    filter_school:        Optional[str] = None,
    filter_study_state:   Optional[str] = None,
    filter_gender:        Optional[str] = None,
    filter_language:      Optional[str] = None,
    # ── 自定义权重（0-100整数，后端归一化）──
    weight_objective:   Optional[int] = None,  # 默认30
    weight_habits:      Optional[int] = None,  # 默认40
    weight_personality: Optional[int] = None,  # 默认30
    # ── 搜索词（传给AI做软匹配）──
    search_query: Optional[str] = None,
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

    # 批量查 email
    user_ids = [p.user_id for p in all_profiles]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    email_map: dict = {u.id: u.email for u in users_result.scalars().all()}

    # 严格筛选（搜索框上方填空）
    has_filters = any([
        filter_study_country, filter_school, filter_study_state,
        filter_gender, filter_language,
    ])
    candidates = (
        hard_filter_profiles(
            all_profiles,
            study_country = filter_study_country,
            school        = filter_school,
            study_state   = filter_study_state,
            gender        = filter_gender,
            language      = filter_language,
        )
        if has_filters else all_profiles
    )
    if has_filters and not candidates:
        return []

    # 搜索词解析 → 硬筛选 + 软查询
    search_filters = parse_search_query(search_query or "")
    soft_query = search_filters.pop("soft_query", None)  # 剩余词传给 AI
    if search_filters:
        candidates = filter_by_search(candidates, search_filters)
        if not candidates:
            return []

    # 自定义权重（归一化到总和=1）
    custom_weights = None
    if any(w is not None for w in [weight_objective, weight_habits, weight_personality]):
        wo = weight_objective   if weight_objective   is not None else 30
        wh = weight_habits      if weight_habits      is not None else 40
        wp = weight_personality if weight_personality is not None else 30
        total_w = wo + wh + wp or 100
        custom_weights = {
            "objective":   wo / total_w,
            "habits":      wh / total_w,
            "personality": wp / total_w,
        }

    # 有筛选/自定义权重/搜索词时强制刷新
    if has_filters or custom_weights or search_query:
        refresh = True

    # 缓存命中（无任何筛选时）
    if not refresh:
        cached = await db.execute(
            select(MatchScore)
            .where(MatchScore.user_id == current_user.id)
            .order_by(MatchScore.total_score.desc())
            .limit(limit)
        )
        cached_scores = cached.scalars().all()
        if len(cached_scores) == len(all_profiles):
            return await _build_match_results(cached_scores, db, email_map)

    semaphore = asyncio.Semaphore(5)  # Qwen并发限制
    # soft_query 在搜索词解析后定义，若无搜索词则为 None
    if 'soft_query' not in dir():
        soft_query = None  # 兜底，正常情况上面已定义

    async def score_one(other: UserProfile):
        async with semaphore:
            obj_score,  obj_reason  = await compute_objective_score(my_profile, other)
            hab_score,  hab_reason  = await compute_habits_score(my_profile, other)
            per_score,  per_reason  = await compute_personality_score(my_profile, other)

        skills_lbl = compute_skills_label(my_profile, other)
        total, weights = compute_total_score(obj_score, hab_score, per_score, custom_weights)

        # 合并评语
        reason_parts = []
        if obj_reason: reason_parts.append(f"📍 客观：{obj_reason}")
        if hab_reason: reason_parts.append(f"🏠 习惯：{hab_reason}")
        if per_reason: reason_parts.append(f"✨ 性格兴趣：{per_reason}")
        match_reason = "\n".join(reason_parts) or None

        return (
            other,
            obj_score, hab_score, per_score,
            skills_lbl, total, weights,
            obj_reason, hab_reason, per_reason,
            match_reason,
        )

    tasks   = [score_one(p) for p in candidates]
    results = await asyncio.gather(*tasks)
    valid   = sorted(results, key=lambda x: x[5], reverse=True)[:limit]

    # 写缓存
    for row in valid:
        (other, obj_score, hab_score, per_score,
         skills_lbl, total, weights,
         obj_reason, hab_reason, per_reason, match_reason) = row

        o = obj_score if obj_score is not None else 50.0
        h = hab_score if hab_score is not None else 50.0
        p = per_score if per_score is not None else 50.0

        existing = await db.execute(
            select(MatchScore).where(
                MatchScore.user_id == current_user.id,
                MatchScore.target_user_id == other.user_id,
            )
        )
        ms = existing.scalar_one_or_none()

        extra = {
            "objective_score":   o,
            "habits_score":      h,
            "personality_score": p,
            "total_score":       total,
            "match_reason":      match_reason,
            # 旧字段兼容
            "rule_score":        h,
            "ai_score":          o,
        }
        if hasattr(MatchScore, "skills_label"):   extra["skills_label"]   = skills_lbl
        if hasattr(MatchScore, "score_weights"):  extra["score_weights"]  = json.dumps(weights)
        if hasattr(MatchScore, "objective_reason"): extra["objective_reason"]   = obj_reason
        if hasattr(MatchScore, "habits_reason"):    extra["habits_reason"]      = hab_reason
        if hasattr(MatchScore, "personality_reason"): extra["personality_reason"] = per_reason

        if ms:
            for k, v in extra.items():
                if hasattr(ms, k):
                    setattr(ms, k, v)
        else:
            kwargs = {
                "user_id":          current_user.id,
                "target_user_id":   other.user_id,
            }
            kwargs.update({k: v for k, v in extra.items() if hasattr(MatchScore, k)})
            db.add(MatchScore(**kwargs))

    await db.commit()

    # 构建返回
    match_results = []
    for row in valid:
        (other, obj_score, hab_score, per_score,
         skills_lbl, total, weights,
         obj_reason, hab_reason, per_reason, match_reason) = row

        o = obj_score if obj_score is not None else 50.0
        h = hab_score if hab_score is not None else 50.0
        p = per_score if per_score is not None else 50.0

        match_results.append(MatchResult(
            user_id             = other.user_id,
            name                = other.name,
            school              = other.school,
            city                = other.city,
            study_country       = other.study_country,
            study_state         = other.study_state,
            native_language     = other.native_language,
            degree              = other.degree,
            major               = other.major,
            gender              = other.gender,
            zodiac              = other.zodiac,
            mbti                = other.mbti,
            sleep_habit         = other.sleep_habit,
            diet_habit          = other.diet_habit,
            food_preference     = other.food_preference,
            habits              = str_to_list(other.habits or ""),
            budget_currency     = other.budget_currency,
            budget_min          = other.budget_min,
            budget_max          = other.budget_max,
            room_types          = str_to_list(other.room_types or ""),
            roommate_experience = other.roommate_experience,
            special_skills      = str_to_list(other.special_skills or ""),
            bio                 = other.bio,
            avatar_url          = other.avatar_url,
            email               = email_map.get(other.user_id),
            total_score         = total,
            objective_score     = round(o),
            habits_score        = round(h),
            personality_score   = round(p),
            skills_label        = skills_lbl,
            score_weights       = weights,
            match_reason        = match_reason,
            objective_reason    = obj_reason,
            habits_reason       = hab_reason,
            personality_reason  = per_reason,
            # 旧字段兼容
            rule_score          = round(h),
            ai_score            = round(o),
        ))
    return match_results


async def _build_match_results(cached_scores, db, email_map: dict = None):
    if email_map is None:
        email_map = {}
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
            try:
                weights = json.loads(ms.score_weights)
            except Exception:
                weights = {}

        o = getattr(ms, "objective_score",   ms.ai_score   if hasattr(ms, "ai_score")   else 50.0)
        h = getattr(ms, "habits_score",      ms.rule_score if hasattr(ms, "rule_score")  else 50.0)
        p = getattr(ms, "personality_score", 50.0)
        sl = getattr(ms, "skills_label", None)

        results.append(MatchResult(
            user_id             = profile.user_id,
            name                = profile.name,
            school              = profile.school,
            city                = profile.city,
            study_country       = profile.study_country,
            study_state         = profile.study_state,
            native_language     = profile.native_language,
            degree              = profile.degree,
            major               = profile.major,
            gender              = profile.gender,
            zodiac              = profile.zodiac,
            mbti                = profile.mbti,
            sleep_habit         = profile.sleep_habit,
            diet_habit          = profile.diet_habit,
            food_preference     = profile.food_preference,
            habits              = str_to_list(profile.habits or ""),
            budget_currency     = profile.budget_currency,
            budget_min          = profile.budget_min,
            budget_max          = profile.budget_max,
            room_types          = str_to_list(profile.room_types or ""),
            roommate_experience = profile.roommate_experience,
            special_skills      = str_to_list(profile.special_skills or ""),
            bio                 = profile.bio,
            avatar_url          = profile.avatar_url,
            email               = email_map.get(profile.user_id),
            total_score         = ms.total_score,
            objective_score     = round(o),
            habits_score        = round(h),
            personality_score   = round(p),
            skills_label        = sl,
            score_weights       = weights or None,
            match_reason        = ms.match_reason,
            objective_reason    = getattr(ms, "objective_reason",   None),
            habits_reason       = getattr(ms, "habits_reason",      None),
            personality_reason  = getattr(ms, "personality_reason", None),
            rule_score          = round(h),
            ai_score            = round(o),
        ))
    return results
