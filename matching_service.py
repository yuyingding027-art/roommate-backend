"""
匹配核心逻辑：
1. rule_score (权重40%)  —— 硬条件：学校/城市/性别/作息/饮食/预算重叠
2. ai_score (权重40%)    —— Gemini分析两人bio/兴趣是否契合
3. personality_score (权重20%) —— Gemini综合判断MBTI+星座组合整体兼容性
"""
import os
import json
import asyncio
import google.generativeai as genai
from database import UserProfile

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def compute_rule_score(me: UserProfile, other: UserProfile) -> float:
    """纯规则匹配，返回0-100"""
    score = 0.0

    # 必须同校同城（否则直接0分）
    if me.school.strip().lower() != other.school.strip().lower():
        return 0.0
    if me.city.strip().lower() != other.city.strip().lower():
        return 0.0

    score += 30  # 同校同城基础分

    # 作息习惯（20分）
    if me.sleep_habit == other.sleep_habit:
        score += 20
    elif "flexible" in [me.sleep_habit, other.sleep_habit]:
        score += 10

    # 饮食习惯（20分）
    if me.diet_habit == other.diet_habit:
        score += 15
        if me.diet_habit == "together" and me.food_preference == other.food_preference:
            score += 5

    # 预算重叠（20分）
    overlap_min = max(me.budget_min, other.budget_min)
    overlap_max = min(me.budget_max, other.budget_max)
    if overlap_max >= overlap_min:
        score += 20

    # 同住经历（10分）—— 经历相近加分
    exp_diff = abs(me.roommate_experience - other.roommate_experience)
    score += max(0, 10 - exp_diff * 2)

    return min(score, 100.0)


async def compute_personality_score(me: UserProfile, other: UserProfile) -> float:
    """
    用 Gemini 综合判断 MBTI + 星座整体兼容性，返回0-100。
    不再分别打分相加，而是让 AI 作为一个整体来权衡。
    例如：MBTI 很匹配但星座冲突明显，整体分数会被拉低，反之亦然。
    """
    if not me.mbti or not other.mbti or not me.zodiac or not other.zodiac:
        return 50.0

    prompt = f"""你是一个舍友兼容性专家。请综合判断以下两人的性格组合作为室友的整体兼容性。

人物A：MBTI={me.mbti}，星座={me.zodiac}
人物B：MBTI={other.mbti}，星座={other.zodiac}

重要原则：
- 请将 MBTI 和星座作为一个整体来判断，不要分别打分再相加。
- 如果 MBTI 很匹配但星座组合有明显冲突，整体分数应该被拉低。
- 如果星座很匹配但 MBTI 组合容易产生摩擦，整体分数也应该被拉低。
- 只有 MBTI 和星座都相对兼容时，才给高分。
- 50分为中等，低于40分表示不建议配对，高于75分表示非常推荐。

只输出JSON：{{"score": 75, "reason": "简要原因（一句话）"}}
score范围0-100，不要输出任何其他内容。"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        return float(data.get("score", 50))
    except Exception:
        return 50.0


async def compute_ai_score(me: UserProfile, other: UserProfile) -> float:
    """用 Gemini 分析两人 bio 的兴趣和生活方式契合度，返回0-100"""
    if not me.bio or not other.bio:
        return 60.0

    prompt = f"""你是一个留学生舍友匹配专家。请分析以下两位同学的个人介绍，判断他们作为舍友的兼容性。

同学A：{me.bio}

同学B：{other.bio}

请从兴趣爱好、生活方式、性格特质三个维度评估。
只输出JSON，格式：{{"score": 75, "reason": "简要原因"}}
score范围0-100。不要输出任何其他内容。"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        return float(data.get("score", 60))
    except Exception:
        return 60.0


def compute_total_score(rule: float, ai: float, personality: float) -> float:
    return rule * 0.4 + ai * 0.4 + personality * 0.2
