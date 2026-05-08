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
    _call_qwen,
)
import asyncio

router = APIRouter()


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


# ══════════════════════════════════════════════════════════
# AI 搜索词解析
# ══════════════════════════════════════════════════════════
async def parse_search_with_ai(search_query: str) -> dict:
    """让 Qwen 把任意语言的搜索词转成结构化筛选条件"""
    if not search_query or not search_query.strip():
        return {}

    prompt = f"""用户输入了舍友搜索词："{search_query}"

请分析这段搜索词（可能是中文、英文、日语或韩语），提取出以下字段的筛选条件。
如果搜索词没有提到某字段，对应值返回null或空数组。

字段说明：
- gender: "male" | "female" | null
- sleep_habit: "early" | "late" | "flexible" | null
- diet_habit: "together"（一起吃）| "separate"（分开吃/各自）| "flexible" | null
- habits_required: 0个或多个，从 ["smoking","no_smoking","pet","no_pet","clean_high","clean_mid","clean_low"] 选择
- skills_keywords: 技能关键词列表（英文小写）
- soft_query: 无法结构化的描述

例子：
- "一起吃饭" → {{"diet_habit":"together","gender":null,"sleep_habit":null,"habits_required":[],"skills_keywords":[],"soft_query":null}}
- "eat together" → {{"diet_habit":"together","gender":null,"sleep_habit":null,"habits_required":[],"skills_keywords":[],"soft_query":null}}
- "分开吃 不抽烟" → {{"diet_habit":"separate","habits_required":["no_smoking"],"gender":null,"sleep_habit":null,"skills_keywords":[],"soft_query":null}}
- "non-smoker female night owl" → {{"gender":"female","sleep_habit":"late","habits_required":["no_smoking"],"diet_habit":null,"skills_keywords":[],"soft_query":null}}

只输出JSON，不输出任何其他内容："""

    data = await asyncio.to_thread(_call_qwen, prompt)
    print(f"🔍 搜索词 '{search_query}' AI解析: {data}")
    return data or {}


# ══════════════════════════════════════════════════════════
# 多语言值标准化对照表（关键 ★）
# ══════════════════════════════════════════════════════════
DIET_SYNONYMS = {
    "together": [
        "together", "一起吃", "一起", "一块吃", "一起吃饭", "一起用餐",
        "eat together", "eat_together",
        "一緒に食べる", "一緒",
        "같이 먹음", "같이먹음", "함께",
    ],
    "separate": [
        "separate", "各自", "各自解决", "分开吃", "各自吃", "不一起", "分开",
        "eat separately", "eat_separately",
        "別々", "各自で",
        "따로", "따로 먹음", "따로먹음",
    ],
    "flexible": [
        "flexible", "不一定", "随意", "都可以", "不固定", "看情况",
        "不規則", "유동적", "상관없음",
    ],
}

SLEEP_SYNONYMS = {
    "early": [
        "early", "早睡", "早起", "早睡早起",
        "early bird", "early_bird",
        "早起き", "朝型",
        "일찍", "아침형",
    ],
    "late": [
        "late", "晚睡", "夜猫", "夜猫子", "熬夜", "晚睡晚起",
        "night owl", "night_owl",
        "夜型", "夜更かし",
        "늦게", "올빼미", "야행성",
    ],
    "flexible": [
        "flexible", "弹性", "弹性作息", "不固定", "不规律",
        "不規則", "유동적",
    ],
}

GENDER_SYNONYMS = {
    "female": [
        "female", "女", "女性", "女生", "f", "girl", "woman",
        "女の子",
        "여성", "여자",
    ],
    "male": [
        "male", "男", "男性", "男生", "m", "boy", "man",
        "男の子",
        "남성", "남자",
    ],
}


def normalize_field(value: str, synonyms: dict) -> Optional[str]:
    """把任意语言/写法的值标准化成 key（如 'together' / 'separate' / 'flexible'）"""
    if not value:
        return None
    v = value.strip().lower()
    for key, syns in synonyms.items():
        if v in [s.lower() for s in syns]:
            return key
    return v


def filter_by_search(all_profiles: list, filters: dict) -> list:
    """
    用 AI 解析出的标准 key 过滤候选人。
    数据库里的值（任意语言）通过 normalize_field 标准化后再比对。
    """
    if not filters:
        return all_profiles

    result = []
    for p in all_profiles:

        # 性别
        if filters.get("gender"):
            if not p.gender:
                continue
            norm = normalize_field(p.gender, GENDER_SYNONYMS)
            if norm != filters["gender"]:
                continue

        # 作息
        if filters.get("sleep_habit"):
            if not p.sleep_habit:
                continue
            norm = normalize_field(p.sleep_habit, SLEEP_SYNONYMS)
            if norm != filters["sleep_habit"]:
                continue

        # 饮食 ★
        if filters.get("diet_habit"):
            if not p.diet_habit:
                continue
            norm = normalize_field(p.diet_habit, DIET_SYNONYMS)
            if norm != filters["diet_habit"]:
                continue

        # 生活习惯标签
        if filters.get("habits_required"):
            ph = set((p.habits or "").split(","))
            if not set(filters["habits_required"]).issubset(ph):
                continue

        # 技能关键词
        if filters.get("skills_keywords"):
            skills_text = (p.special_skills or "").lower()
            bio_text    = (p.bio or "").lower()
            combined    = skills_text + " " + bio_text
            if not all(kw.lower() in combined for kw in filters["skills_keywords"]):
                continue

        result.append(p)
    return result


# ══════════════════════════════════════════════════════════
# 搜索框上方填空的严格筛选
# ══════════════════════════════════════════════════════════
def hard_filter_profiles(
    all_profiles: list,
    study_country: Optional[str] = None,
    school:        Optional[str] = None,
    study_state:   Optional[str] = None,
    gender:        Optional[str] = None,
    language:      Optional[str] = None,
) -> list:
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
            norm = normalize_field(p.gender, GENDER_SYNONYMS)
            if norm != normalize_field(gender, GENDER_SYNONYMS):
                continue
        if language:
            if not p.native_language:
                continue
            if p.native_language.strip().lower() != language.strip().lower():
                continue
        result.append(p)
    return result


# ══════════════════════════════════════════════════════════
# 主路由
# ══════════════════════════════════════════════════════════
@router.get("/", response_model=List[MatchResult])
async def get_matches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    refresh: bool = False,
    filter_study_country: Optional[str] = None,
    filter_school:        Optional[str] = None,
    filter_study_state:   Optional[str] = None,
    filter_gender:        Optional[str] = None,
    filter_language:      Optional[str] = None,
    weight_objective:   Optional[int] = None,
    weight_habits:      Optional[int] = None,
    weight_personality: Optional[int] = None,
    search_query: Optional[str] = None,
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    my_profile = result.scalar_one_or_none()
    if not my_profile:
        raise HTTPException(status_code=400, detail="请先完善个人资料")

    all_result = await db.execute(
        select(UserProfile).where(
            UserProfile.user_id != current_user.id,
            UserProfile.is_searchable == True,
        )
    )
    all_profiles = all_result.scalars().all()
    if not all_profiles:
        return []

    user_ids = [p.user_id for p in all_profiles]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    email_map: dict = {u.id: u.email for u in users_result.scalars().all()}

    # 严格筛选
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

    # AI 搜索词解析 → 智能筛选
    soft_query = None
    if search_query and search_query.strip():
        parsed = await parse_search_with_ai(search_query)
        if parsed:
            soft_query = parsed.pop("soft_query", None)
            cleaned = {k: v for k, v in parsed.items() if v not in (None, [], "")}
            if cleaned:
                candidates = filter_by_search(candidates, cleaned)
                print(f"🔍 筛选后剩 {len(candidates)} 人，条件={cleaned}")
                if not candidates:
                    return []

    # 自定义权重
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

    if has_filters or custom_weights or search_query:
        refresh = True

    # 缓存
    cached_result = await db.execute(
        select(MatchScore).where(MatchScore.user_id == current_user.id)
    )
    cache_map: dict = {ms.target_user_id: ms for ms in cached_result.scalars().all()}
    my_version = getattr(my_profile, "profile_version", 1) or 1

    if not refresh:
        all_from_cache = True
        for p in candidates:
            ms = cache_map.get(p.user_id)
            if not ms:
                all_from_cache = False
                break
            expected_version = f"v{my_version}_{getattr(p, 'profile_version', 1) or 1}"
            if getattr(ms, "score_version", None) != expected_version:
                all_from_cache = False
                break

        if all_from_cache:
            candidate_ids = {p.user_id for p in candidates}
            cached_scores = sorted(cache_map.values(), key=lambda x: x.total_score, reverse=True)
            cached_scores = [ms for ms in cached_scores if ms.target_user_id in candidate_ids][:limit]
            return await _build_match_results(cached_scores, db, email_map)

    semaphore = asyncio.Semaphore(5)

    async def score_one(other: UserProfile):
        async with semaphore:
            obj_score, obj_reason = await compute_objective_score(my_profile, other)
            hab_score, hab_reason = await compute_habits_score(my_profile, other)
            per_score, per_reason = await compute_personality_score(my_profile, other)

        skills_lbl = compute_skills_label(my_profile, other)
        total, weights = compute_total_score(obj_score, hab_score, per_score, custom_weights)

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
            "rule_score":        h,
            "ai_score":          o,
            "score_version":     f"v{my_version}_{getattr(other, 'profile_version', 1) or 1}",
        }
        if hasattr(MatchScore, "skills_label"):       extra["skills_label"]       = skills_lbl
        if hasattr(MatchScore, "score_weights"):      extra["score_weights"]      = json.dumps(weights)
        if hasattr(MatchScore, "objective_reason"):   extra["objective_reason"]   = obj_reason
        if hasattr(MatchScore, "habits_reason"):      extra["habits_reason"]      = hab_reason
        if hasattr(MatchScore, "personality_reason"): extra["personality_reason"] = per_reason

        if ms:
            for k, v in extra.items():
                if hasattr(ms, k):
                    setattr(ms, k, v)
        else:
            kwargs = {"user_id": current_user.id, "target_user_id": other.user_id}
            kwargs.update({k: v for k, v in extra.items() if hasattr(MatchScore, k)})
            db.add(MatchScore(**kwargs))

    await db.commit()

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

        o  = getattr(ms, "objective_score",   getattr(ms, "ai_score",   50.0))
        h  = getattr(ms, "habits_score",      getattr(ms, "rule_score", 50.0))
        p  = getattr(ms, "personality_score", 50.0)
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
