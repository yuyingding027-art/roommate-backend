"""
匹配核心逻辑 v4 — 三维度体系
══════════════════════════════════════════════════════════
默认权重：
  objective_score   客观信息   30%  —— Qwen（学校/专业/预算/老家/bio客观部分）
  habits_score      生活习惯   40%  —— Qwen（习惯选项 + bio生活习惯部分）
  personality_score 性格兴趣   30%  —— Qwen（MBTI/星座/bio性格兴趣部分）

技能：不参与评分，只返回 skills_label = "相同" | "互补" | None

缺失规则：某维度数据为空 → 该维度权重降为 5%，其余等比扩大

总分 = w_obj * objective + w_hab * habits + w_per * personality
══════════════════════════════════════════════════════════
"""

import os
import json
import asyncio
from openai import OpenAI
from database import UserProfile

# ── Qwen 客户端 ────────────────────────────────────────────
qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",#https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1
)

DEFAULT_WEIGHTS = {
    "objective":   0.30,
    "habits":      0.40,
    "personality": 0.30,
}
MIN_WEIGHT = 0.05


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


def _call_qwen(prompt: str) -> dict:
    """同步调用 Qwen，返回解析后的 dict，失败返回 {}"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ DASHSCOPE_API_KEY 未设置")
        return {}
    try:
        resp = qwen_client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"❌ JSON解析失败，原文: {text[:200]}")
            return {}
    except Exception as e:
        print(f"❌ Qwen调用失败: {type(e).__name__}: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# 维度 1：客观信息（Qwen，综合学校/专业/预算/老家/bio客观部分）
# ══════════════════════════════════════════════════════════
async def compute_objective_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    """
    返回 (score 0-100, reason)。
    两人关键客观字段都为空时返回 (None, None) → 触发降权。
    """
    has_data = any([
        me.school, me.major, me.study_country, me.study_state,
        me.budget_max, me.nationality, me.native_language, me.bio,
    ])
    if not has_data:
        return None, None

    prompt = f"""你是留学生舍友匹配专家。请根据以下两位同学的客观基本信息，评估他们作为舍友的客观条件匹配程度。

评估维度（重要性从高到低）：
1. 留学国家/学校/校区/专业是否相同或相近
2. 租房预算是否接近（差距越小越好）
3. 老家/国籍/母语是否相同
4. 个人介绍中提到的学校、专业、老家、背景等客观信息

A的信息：
- 学校：{me.school or '未填写'}
- 专业：{me.major or '未填写'}
- 留学国家：{me.study_country or '未填写'}
- 校区/州：{me.study_state or '未填写'}
- 城市：{me.city or '未填写'}
- 预算上限：{me.budget_max or '未填写'} {me.budget_currency or ''}
- 国籍：{me.nationality or '未填写'}
- 母语：{me.native_language or '未填写'}
- 个人介绍：{me.bio or '未填写'}

B的信息：
- 学校：{other.school or '未填写'}
- 专业：{other.major or '未填写'}
- 留学国家：{other.study_country or '未填写'}
- 校区/州：{other.study_state or '未填写'}
- 城市：{other.city or '未填写'}
- 预算上限：{other.budget_max or '未填写'} {other.budget_currency or ''}
- 国籍：{other.nationality or '未填写'}
- 母语：{other.native_language or '未填写'}
- 个人介绍：{other.bio or '未填写'}

评分标准：满分100，完全一致的关键信息（同校同专业同预算范围）接近100，完全不同接近0。
只输出JSON：{{"score": 75, "reason": "一句话说明主要匹配或不匹配的点"}}
不输出任何其他内容。"""

    data = await asyncio.to_thread(_call_qwen, prompt)
    if not data:
        return 50.0, None
    return float(data.get("score", 50)), data.get("reason")


# ══════════════════════════════════════════════════════════
# 维度 2：生活习惯（Qwen，习惯选项 + bio生活习惯部分）
# ══════════════════════════════════════════════════════════
async def compute_habits_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    """
    返回 (score 0-100, reason)。
    习惯数据完全为空时返回 (None, None)。
    """
    has_data = any([
        me.sleep_habit, me.diet_habit, me.habits, me.bio,
    ])
    if not has_data:
        return None, None

    my_habits = str_to_list(me.habits or "")
    oth_habits = str_to_list(other.habits or "")

    prompt = f"""你是留学生舍友匹配专家。请根据以下两位同学的生活习惯信息，评估他们作为舍友的生活习惯契合程度。

评估维度（重要性从高到低）：
1. 作息时间（早睡早起 vs 晚睡晚起）——冲突最影响同住体验
2. 生活习惯标签（抽烟/不抽烟、有宠物/不接受宠物、整洁程度）——有冲突大幅扣分
3. 饮食习惯（一起吃/各自解决/外卖）
4. 个人介绍中关于作息、卫生、宠物、带人进家等生活方式描述

A的生活习惯：
- 作息：{me.sleep_habit or '未填写'}
- 饮食：{me.diet_habit or '未填写'}{f'（偏好：{me.food_preference}）' if me.food_preference else ''}
- 生活习惯标签：{', '.join(my_habits) if my_habits else '未填写'}
- 个人介绍：{me.bio or '未填写'}

B的生活习惯：
- 作息：{other.sleep_habit or '未填写'}
- 饮食：{other.diet_habit or '未填写'}{f'（偏好：{other.food_preference}）' if other.food_preference else ''}
- 生活习惯标签：{', '.join(oth_habits) if oth_habits else '未填写'}
- 个人介绍：{other.bio or '未填写'}

重要规则：
- 抽烟 vs 不抽烟：严重冲突，大幅扣分（-30以上）
- 有宠物 vs 不接受宠物：严重冲突，大幅扣分（-25以上）
- 极度爱干净 vs 不在乎卫生：严重冲突，扣分（-20以上）
- 作息差异超过3小时：明显冲突，扣分（-15以上）

评分标准：满分100，完全无冲突且高度相似接近100，有严重冲突接近0。
只输出JSON：{{"score": 75, "reason": "一句话说明主要匹配或冲突点"}}
不输出任何其他内容。"""

    data = await asyncio.to_thread(_call_qwen, prompt)
    if not data:
        return 50.0, None
    return float(data.get("score", 50)), data.get("reason")


# ══════════════════════════════════════════════════════════
# 维度 3：性格兴趣（Qwen，MBTI + 星座 + bio性格兴趣部分）
# ══════════════════════════════════════════════════════════
async def compute_personality_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    """
    返回 (score 0-100, reason)。
    MBTI、星座、bio 全部为空时返回 (None, None)。
    """
    has_data = any([me.mbti, me.zodiac, me.bio])
    if not has_data:
        return None, None

    prompt = f"""你是留学生舍友匹配专家，熟悉权威的MBTI兼容性研究和星座性格分析。
请综合评估以下两位同学的性格与兴趣爱好契合程度，作为判断舍友相处是否愉快的依据。

评估维度：
1. MBTI性格类型兼容性（基于权威MBTI配对研究：如INFJ与ENFP高度互补，ENTJ与INTP良好等）
2. 星座性格兼容性（综合判断，不要机械对应）
3. 个人介绍中关于性格、爱好、生活态度、兴趣的描述

A的性格兴趣：
- MBTI：{me.mbti or '未填写'}
- 星座：{me.zodiac or '未填写'}
- 个人介绍：{me.bio or '未填写'}

B的性格兴趣：
- MBTI：{other.mbti or '未填写'}
- 星座：{other.zodiac or '未填写'}
- 个人介绍：{other.bio or '未填写'}

评分标准：满分100，性格高度互补或相似且兴趣有共鸣接近100，性格严重冲突接近0，50分为中等兼容。
只输出JSON：{{"score": 75, "reason": "一句话说明性格兴趣匹配情况"}}
不输出任何其他内容。"""

    data = await asyncio.to_thread(_call_qwen, prompt)
    if not data:
        return 50.0, None
    return float(data.get("score", 50)), data.get("reason")


# ══════════════════════════════════════════════════════════
# 技能标签（不参与评分）
# ══════════════════════════════════════════════════════════
def compute_skills_label(me: UserProfile, other: UserProfile) -> str | None:
    """
    返回 "相同" | "互补" | None（双方都没有技能时）
    """
    my_skills  = set(s.strip().lower() for s in str_to_list(me.special_skills  or ""))
    oth_skills = set(s.strip().lower() for s in str_to_list(other.special_skills or ""))

    if not my_skills and not oth_skills:
        return None

    common = my_skills & oth_skills
    # 有任何共同技能 → 相同；否则 → 互补
    if common:
        return "相同"
    return "互补"


# ══════════════════════════════════════════════════════════
# 权重计算 + 总分
# ══════════════════════════════════════════════════════════
def resolve_weights(
    objective_score:   float | None,
    habits_score:      float | None,
    personality_score: float | None,
    custom_weights:    dict | None = None,
) -> dict[str, float]:
    """
    custom_weights 格式：{"objective": 0.3, "habits": 0.4, "personality": 0.3}
    缺失维度固定 MIN_WEIGHT，其余按 custom 或 default 比例等比扩大。
    """
    base = custom_weights if custom_weights else dict(DEFAULT_WEIGHTS)

    missing = []
    if objective_score   is None: missing.append("objective")
    if habits_score      is None: missing.append("habits")
    if personality_score is None: missing.append("personality")

    if not missing:
        # 归一化 base（防止用户自定义权重不等于1）
        total = sum(base.values())
        return {k: v / total for k, v in base.items()}

    reserved    = MIN_WEIGHT * len(missing)
    pool        = 1.0 - reserved
    present     = {k: v for k, v in base.items() if k not in missing}
    present_sum = sum(present.values()) or 1.0

    weights = {k: v / present_sum * pool for k, v in present.items()}
    for k in missing:
        weights[k] = MIN_WEIGHT
    return weights


def compute_total_score(
    objective_score:   float | None,
    habits_score:      float | None,
    personality_score: float | None,
    custom_weights:    dict | None = None,
) -> tuple[float, dict[str, float]]:
    """
    返回 (total_0_100, weights_used)
    """
    w = resolve_weights(objective_score, habits_score, personality_score, custom_weights)

    o = objective_score   if objective_score   is not None else 50.0
    h = habits_score      if habits_score      is not None else 50.0
    p = personality_score if personality_score is not None else 50.0

    total = o * w["objective"] + h * w["habits"] + p * w["personality"]
    return round(min(total, 100.0), 1), w
