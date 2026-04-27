"""
匹配核心逻辑：
1. rule_score (动态权重) —— 硬条件：学校/城市/语言/专业/作息/饮食/预算/习惯
2. ai_score (动态权重)   —— Gemini分析bio契合度 + 搜索词匹配
3. personality_score (动态权重) —— Gemini综合判断MBTI+星座整体兼容性
权重依据用户勾选的priorities动态调整
"""
import os
import json
import asyncio
import google.generativeai as genai
from database import UserProfile

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def str_to_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


def compute_rule_score(me: UserProfile, other: UserProfile, priorities: list = None) -> float:
    """纯规则匹配，返回0-100，依据priorities调整权重"""
    if priorities is None:
        priorities = ["city", "school", "major", "language", "habits", "budget", "special_skills"]

    score = 0.0
    max_score = 0.0

    # 同城（20分）
    if "city" in priorities:
        max_score += 20
        if me.city and other.city and me.city.strip().lower() == other.city.strip().lower():
            score += 20

    # 同校（20分）
    if "school" in priorities:
        max_score += 20
        if me.school and other.school and me.school.strip().lower() == other.school.strip().lower():
            score += 20

    # 同专业（10分）
    if "major" in priorities:
        max_score += 10
        if me.major and other.major and me.major.strip().lower() == other.major.strip().lower():
            score += 10

    # 同语言（10分）
    if "language" in priorities:
        max_score += 10
        if me.native_language and other.native_language and me.native_language == other.native_language:
            score += 10

    # 作息习惯（15分）
    if "habits" in priorities:
        max_score += 15
        if me.sleep_habit == other.sleep_habit:
            score += 15
        elif "flexible" in [me.sleep_habit, other.sleep_habit]:
            score += 7

    # 饮食习惯（10分）
    if "habits" in priorities:
        max_score += 10
        if me.diet_habit == other.diet_habit:
            score += 8
            if me.diet_habit == "together" and me.food_preference == other.food_preference:
                score += 2

    # 生活习惯冲突检测（15分）
    if "habits" in priorities:
        max_score += 15
        my_habits = set(str_to_list(me.habits or ""))
        other_habits = set(str_to_list(other.habits or ""))
        conflicts = 0
        if "smoking" in my_habits and "no_smoking" in other_habits:
            conflicts += 1
        if "no_smoking" in my_habits and "smoking" in other_habits:
            conflicts += 1
        if "pet" in my_habits and "no_pet" in other_habits:
            conflicts += 1
        if "no_pet" in my_habits and "pet" in other_habits:
            conflicts += 1
        my_clean = my_habits & {"clean_high", "clean_mid", "clean_low"}
        other_clean = other_habits & {"clean_high", "clean_mid", "clean_low"}
        if my_clean and other_clean and my_clean != other_clean:
            if ("clean_high" in my_clean and "clean_low" in other_clean) or \
               ("clean_low" in my_clean and "clean_high" in other_clean):
                conflicts += 1
        if conflicts == 0:
            score += 15
        elif conflicts == 1:
            score += 5

    # 预算（15分）
    if "budget" in priorities:
        max_score += 15
        my_max = me.budget_max or 0
        other_max = other.budget_max or 0
        if my_max > 0 and other_max > 0:
            diff_ratio = abs(my_max - other_max) / max(my_max, other_max)
            if diff_ratio <= 0.2:
                score += 15
            elif diff_ratio <= 0.4:
                score += 8

    # 特殊技能（10分）
    if "special_skills" in priorities:
        max_score += 10
        my_skills = set(str_to_list(me.special_skills or ""))
        other_skills = set(str_to_list(other.special_skills or ""))
        common = my_skills & other_skills
        score += min(len(common) * 3, 10)

    if max_score == 0:
        return 50.0
    return min((score / max_score) * 100, 100.0)


async def compute_personality_score(me: UserProfile, other: UserProfile) -> tuple:
    """Gemini综合判断MBTI+星座整体兼容性，返回(score, reason)"""
    if not me.mbti or not other.mbti or not me.zodiac or not other.zodiac:
        return 50.0, None

    prompt = f"""你是一个舍友兼容性专家。请综合判断以下两人的性格组合作为室友的整体兼容性。

人物A：MBTI={me.mbti}，星座={me.zodiac}
人物B：MBTI={other.mbti}，星座={other.zodiac}

重要原则：
- 将MBTI和星座作为整体判断，不要分别打分相加
- MBTI很匹配但星座冲突明显，整体分数应被拉低
- 只有两者都相对兼容时才给高分
- 50分为中等，低于40不建议，高于75非常推荐

只输出JSON：{{"score": 75, "reason": "简要原因（一句话）"}}
score范围0-100，不要输出任何其他内容。"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        return float(data.get("score", 50)), data.get("reason")
    except Exception:
        return 50.0, None


async def compute_ai_score(me: UserProfile, other: UserProfile, search_query: str = None, priorities: list = None) -> tuple:
    """Gemini分析bio契合度，返回(score, reason_str)"""
    if not me.bio and not other.bio and not search_query:
        return 60.0, None

    search_part = f"\n用户搜索词：{search_query}（请重点评估对方是否符合这个描述）" if search_query else ""
    priority_part = f"\n用户最看重：{', '.join(priorities)}（请在评估时重点考虑这些维度）" if priorities else ""

    prompt = f"""你是一个留学生舍友匹配专家。请分析以下两位同学作为舍友的兼容性。{search_part}{priority_part}

同学A的介绍：{me.bio or '未填写'}
同学B的介绍：{other.bio or '未填写'}

请综合评估，列出匹配和不匹配的点。
只输出JSON：{{"score": 75, "match": ["匹配点1", "匹配点2"], "unmatch": ["不匹配点1"], "reason": "总体原因一句话"}}
score范围0-100，不要输出任何其他内容。"""

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        match_points = data.get("match", [])
        unmatch_points = data.get("unmatch", [])
        reason = data.get("reason", "")
        full_reason = ""
        if match_points:
            full_reason += "✅ 匹配：" + "、".join(match_points) + "\n"
        if unmatch_points:
            full_reason += "❌ 不匹配：" + "、".join(unmatch_points) + "\n"
        if reason:
            full_reason += "💡 " + reason
        return float(data.get("score", 60)), full_reason.strip() or None
    except Exception:
        return 60.0, None


def compute_total_score(rule: float, ai: float, personality: float, priorities: list = None) -> float:
    """依据priorities动态调整权重"""
    if not priorities:
        return rule * 0.4 + ai * 0.4 + personality * 0.2

    has_personality = any(p in priorities for p in ["mbti", "zodiac"])
    has_bio = any(p in priorities for p in ["bio", "interests", "special_skills"])

    if has_personality and has_bio:
        return rule * 0.34 + ai * 0.33 + personality * 0.33
    elif has_personality:
        return rule * 0.4 + ai * 0.3 + personality * 0.3
    elif has_bio:
        return rule * 0.3 + ai * 0.5 + personality * 0.2
    else:
        return rule * 0.4 + ai * 0.4 + personality * 0.2
