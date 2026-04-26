"""
匹配核心逻辑：
1. rule_score (权重40%)  —— 硬条件：学校/城市/性别/作息/饮食/预算重叠
2. ai_score (权重40%)    —— Claude分析两人bio/兴趣是否契合
3. personality_score (权重20%) —— Claude判断MBTI+星座组合兼容性
"""
import os
import json
#import anthropic
import google.generativeai as genai
from database import UserProfile

#client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

MBTI_COMPATIBILITY = {
    "INTJ": ["ENFP", "ENTP", "INTJ", "INFJ"],
    "INTP": ["ENTJ", "ENFJ", "INTP", "INFP"],
    "ENTJ": ["INTP", "INFP", "ENTJ", "INTJ"],
    "ENTP": ["INTJ", "INFJ", "ENTP", "INTP"],
    "INFJ": ["ENTP", "ENFP", "INFJ", "INTJ"],
    "INFP": ["ENTJ", "ENFJ", "INFP", "INTP"],
    "ENFJ": ["INTP", "INFP", "ENFJ", "INFJ"],
    "ENFP": ["INTJ", "INFJ", "ENFP", "INFJ"],
    "ISTJ": ["ESFP", "ESTP", "ISTJ", "ISFJ"],
    "ISFJ": ["ESFP", "ESTP", "ISFJ", "ISTJ"],
    "ESTJ": ["ISFP", "ISTP", "ESTJ", "ESFJ"],
    "ESFJ": ["ISFP", "ISTP", "ESFJ", "ESTJ"],
    "ISTP": ["ESFJ", "ESTJ", "ISTP", "ISFP"],
    "ISFP": ["ESTJ", "ESFJ", "ISFP", "ISTP"],
    "ESTP": ["ISFJ", "ISTJ", "ESTP", "ESFP"],
    "ESFP": ["ISFJ", "ISTJ", "ESFP", "ESTP"],
}

ZODIAC_COMPATIBILITY = {
    "白羊座": ["狮子座", "射手座", "双子座", "水瓶座"],
    "金牛座": ["处女座", "摩羯座", "巨蟹座", "双鱼座"],
    "双子座": ["天秤座", "水瓶座", "白羊座", "狮子座"],
    "巨蟹座": ["天蝎座", "双鱼座", "金牛座", "处女座"],
    "狮子座": ["白羊座", "射手座", "双子座", "天秤座"],
    "处女座": ["金牛座", "摩羯座", "巨蟹座", "天蝎座"],
    "天秤座": ["双子座", "水瓶座", "狮子座", "射手座"],
    "天蝎座": ["巨蟹座", "双鱼座", "处女座", "摩羯座"],
    "射手座": ["白羊座", "狮子座", "天秤座", "水瓶座"],
    "摩羯座": ["金牛座", "处女座", "天蝎座", "双鱼座"],
    "水瓶座": ["双子座", "天秤座", "白羊座", "射手座"],
    "双鱼座": ["巨蟹座", "天蝎座", "金牛座", "摩羯座"],
}

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

def compute_personality_score(me: UserProfile, other: UserProfile) -> float:
    """MBTI + 星座静态兼容表，返回0-100"""
    score = 50.0  # 默认中等

    mbti_bonus = 0
    if me.mbti and other.mbti:
        compatible_list = MBTI_COMPATIBILITY.get(me.mbti.upper(), [])
        if other.mbti.upper() in compatible_list:
            mbti_bonus = 25
        elif me.mbti.upper() == other.mbti.upper():
            mbti_bonus = 15

    zodiac_bonus = 0
    if me.zodiac and other.zodiac:
        compatible_list = ZODIAC_COMPATIBILITY.get(me.zodiac, [])
        if other.zodiac in compatible_list:
            zodiac_bonus = 25
        elif me.zodiac == other.zodiac:
            zodiac_bonus = 10

    score = 50 + mbti_bonus + zodiac_bonus
    return min(score, 100.0)

async def compute_ai_score(me: UserProfile, other: UserProfile) -> float:
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
