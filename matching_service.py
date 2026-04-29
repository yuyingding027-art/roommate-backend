"""
匹配核心逻辑 v3 — 五维度体系
══════════════════════════════════════════════════════════
默认权重（五项数据都完整时）：
  1. habits_score      生活习惯  25%  —— 纯规则
  2. objective_score   客观信息  25%  —— 纯规则
  3. skills_score      技能      20%  —— 纯规则
  4. personality_score 性格      15%  —— Qwen (MBTI + 星座)
  5. interest_score    兴趣爱好  15%  —— Qwen (bio)

缺失规则：
  - 某维度数据为空 → 该维度权重降为 5%（最低保底）
  - 剩余权重按各维度默认比例等比扩大，补齐到 100%

分数细则
──────────────────────────────────────────────────────────
habits_score (0-100, 纯规则)
  作息完全相同           +40
  一方弹性               +20
  饮食完全相同           +25  (含口味偏好 +5)
  无生活冲突             +35 / 1条冲突 +10 / 2+条冲突 0
  满分=100，按比例归一化

objective_score (0-100, 纯规则)
  同校                   +40 (最高权)
  同校区/study_state     +20
  同专业                 +25
  预算差≤20%             +15 / ≤40% +8
  满分=100，按比例归一化

skills_score (0-100, 纯规则)
  共同技能: 每个 +20，最高 100
  无技能数据 → 返回 None，触发降权

personality_score (0-100, Qwen)
  MBTI + 星座综合判断
  任一缺失 → 返回 None，触发降权

interest_score (0-100, Qwen)
  bio 兴趣分析
  两人都无 bio → 返回 None，触发降权
══════════════════════════════════════════════════════════
"""

import os
import json
import asyncio
from openai import OpenAI
from database import UserProfile

# ── Qwen 客户端（阿里云国际版，香港节点）────────────────────────────────────
qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",  # ← 改这里
)

# ── 默认权重 ──────────────────────────────────────────────
DEFAULT_WEIGHTS = {
    "habits":      0.25,
    "objective":   0.25,
    "skills":      0.20,
    "personality": 0.15,
    "interest":    0.15,
}
MIN_WEIGHT = 0.05  # 缺失维度的保底权重


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


# ══════════════════════════════════════════════════════════
# 维度 1：生活习惯（纯规则）
# ══════════════════════════════════════════════════════════
def compute_habits_score(me: UserProfile, other: UserProfile) -> float:
    """
    返回 0-100。
    作息(40) + 饮食(25) + 冲突检测(35) = 满分 100
    """
    score = 0.0

    # 作息（满分 40）
    if me.sleep_habit and other.sleep_habit:
        if me.sleep_habit == other.sleep_habit:
            score += 40
        elif "flexible" in (me.sleep_habit, other.sleep_habit):
            score += 20

    # 饮食（满分 25）
    if me.diet_habit and other.diet_habit:
        if me.diet_habit == other.diet_habit:
            score += 20
            if (me.diet_habit == "together"
                    and me.food_preference and other.food_preference
                    and me.food_preference == other.food_preference):
                score += 5
        else:
            casual = {"separate", "flexible", "各自解决"}
            if me.diet_habit in casual and other.diet_habit in casual:
                score += 8

    # 生活习惯冲突（满分 35）
    my_h  = set(str_to_list(me.habits or ""))
    oth_h = set(str_to_list(other.habits or ""))
    conflicts = 0
    pairs = [("smoking", "no_smoking"), ("pet", "no_pet")]
    for a, b in pairs:
        if (a in my_h and b in oth_h) or (b in my_h and a in oth_h):
            conflicts += 1
    my_clean  = my_h  & {"clean_high", "clean_mid", "clean_low"}
    oth_clean = oth_h & {"clean_high", "clean_mid", "clean_low"}
    if my_clean and oth_clean and my_clean != oth_clean:
        if (("clean_high" in my_clean and "clean_low" in oth_clean)
                or ("clean_low" in my_clean and "clean_high" in oth_clean)):
            conflicts += 1
    if conflicts == 0:
        score += 35
    elif conflicts == 1:
        score += 10

    return min(score, 100.0)


# ══════════════════════════════════════════════════════════
# 维度 2：客观信息（纯规则）
# ══════════════════════════════════════════════════════════
def compute_objective_score(me: UserProfile, other: UserProfile) -> float:
    """
    返回 0-100。
    同校(40) + 同校区(20) + 同专业(25) + 预算(15) = 满分 100
    """
    score = 0.0

    # 同校（40）
    if (me.school and other.school
            and me.school.strip().lower() == other.school.strip().lower()):
        score += 40

    # 同校区 / study_state（20）
    if (me.study_state and other.study_state
            and me.study_state.strip().lower() == other.study_state.strip().lower()):
        score += 20

    # 同专业（25）
    if (me.major and other.major
            and me.major.strip().lower() == other.major.strip().lower()):
        score += 25

    # 预算差距（15）
    my_max  = me.budget_max  or 0
    oth_max = other.budget_max or 0
    if my_max > 0 and oth_max > 0:
        diff = abs(my_max - oth_max) / max(my_max, oth_max)
        if diff <= 0.20:
            score += 15
        elif diff <= 0.40:
            score += 8

    return min(score, 100.0)


# ══════════════════════════════════════════════════════════
# 维度 3：技能（纯规则）
# ══════════════════════════════════════════════════════════
def compute_skills_score(me: UserProfile, other: UserProfile) -> float | None:
    """
    返回 0-100，或 None（两人都无技能数据时触发降权）。
    共同技能每个 +20，上限 100。
    """
    my_skills  = set(s.strip().lower() for s in str_to_list(me.special_skills  or ""))
    oth_skills = set(s.strip().lower() for s in str_to_list(other.special_skills or ""))

    if not my_skills and not oth_skills:
        return None  # 触发降权

    common = my_skills & oth_skills
    return min(len(common) * 20, 100.0)


# ══════════════════════════════════════════════════════════
# 维度 4：性格（Qwen）
# ══════════════════════════════════════════════════════════
async def compute_personality_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    """
    返回 (score, reason)。
    MBTI 或星座缺失时返回 (None, None) → 调用方触发降权。
    """
    if not me.mbti or not other.mbti or not me.zodiac or not other.zodiac:
        return None, None

    prompt = (
        "你是一个舍友兼容性专家。请综合判断以下两人的性格作为室友的整体兼容性。\n\n"
        f"人物A：MBTI={me.mbti}，星座={me.zodiac}\n"
        f"人物B：MBTI={other.mbti}，星座={other.zodiac}\n\n"
        "原则：整体判断，不要分别打分相加；50分为中等；低于40不建议；高于75推荐。\n"
        '只输出JSON：{"score": 75, "reason": "一句话"}\n'
        "score范围0-100，不输出任何其他内容。"
    )
    try:
        resp = await asyncio.to_thread(
            lambda: qwen_client.chat.completions.create(
                model="qwen-plus",
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        return float(data.get("score", 50)), data.get("reason")
    except Exception as e:
        print(f"Qwen personality API 调用失败: {e}")
        return 50.0, None


# ══════════════════════════════════════════════════════════
# 维度 5：兴趣爱好（Qwen）
# ══════════════════════════════════════════════════════════
async def compute_interest_score(
    me: UserProfile, other: UserProfile, search_query: str = None
) -> tuple[float | None, str | None]:
    """
    返回 (score, reason)。
    两人都无 bio 时返回 (None, None) → 调用方触发降权。
    """
    if not me.bio and not other.bio and not search_query:
        return None, None

    sq_part = f"\n搜索词补充：{search_query}" if search_query else ""
    prompt = (
        f"你是留学生舍友兴趣匹配专家。请分析两位同学在兴趣爱好、个人风格方面的契合度。{sq_part}\n\n"
        f"A的介绍：{me.bio or '未填写'}\n"
        f"B的介绍：{other.bio or '未填写'}\n\n"
        "评估共同话题、生活风格、价值观契合度。\n"
        '只输出JSON：{"score": 70, "match": ["共同点1"], "reason": "一句话"}\n'
        "score范围0-100，不输出其他内容。"
    )
    data = {}  # ← 加这行
    try:
        resp = await asyncio.to_thread(
            lambda: qwen_client.chat.completions.create(
                model="qwen-plus",
                messages=[{"role": "user", "content": prompt}],
            )
        )
        print(f"✅ Qwen interest 调用成功，score={data.get('score')}")  # 加这行
        text = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        pts  = data.get("match", [])
        rsn  = data.get("reason", "")
        full = ""
        if pts: full += "🎯 共同点：" + "、".join(pts)
        if rsn: full += ("\n" if full else "") + "💡 " + rsn
        return float(data.get("score", 60)), full.strip() or None
    except Exception as e:
        print(f"Qwen interest API 调用失败: {e}")
        return 60.0, None


# ══════════════════════════════════════════════════════════
# 权重计算 + 总分合并
# ══════════════════════════════════════════════════════════
def resolve_weights(
    skills_score:      float | None,
    personality_score: float | None,
    interest_score:    float | None,
) -> dict[str, float]:
    missing = []
    if skills_score      is None: missing.append("skills")
    if personality_score is None: missing.append("personality")
    if interest_score    is None: missing.append("interest")

    if not missing:
        return dict(DEFAULT_WEIGHTS)

    reserved    = MIN_WEIGHT * len(missing)
    pool        = 1.0 - reserved
    present     = {k: v for k, v in DEFAULT_WEIGHTS.items() if k not in missing}
    present_sum = sum(present.values())

    weights = {k: v / present_sum * pool for k, v in present.items()}
    for k in missing:
        weights[k] = MIN_WEIGHT
    return weights


def compute_total_score(
    habits_score:      float,
    objective_score:   float,
    skills_score:      float | None,
    personality_score: float | None,
    interest_score:    float | None,
) -> tuple[float, dict[str, float]]:
    w = resolve_weights(skills_score, personality_score, interest_score)

    s_skills      = skills_score      if skills_score      is not None else 50.0
    s_personality = personality_score if personality_score is not None else 50.0
    s_interest    = interest_score    if interest_score    is not None else 50.0

    total = (
        habits_score    * w["habits"]      +
        objective_score * w["objective"]   +
        s_skills        * w["skills"]      +
        s_personality   * w["personality"] +
        s_interest      * w["interest"]
    )
    return round(min(total, 100.0), 1), w


# ── 旧接口兼容 ──────────────────────────────────────────────
def compute_rule_score(me, other, priorities=None):
    return compute_habits_score(me, other)

async def compute_ai_score(me, other, search_query=None, priorities=None):
    return await compute_interest_score(me, other, search_query)
