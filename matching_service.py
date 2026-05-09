"""
Matching engine v5
══════════════════════════════════════════════════════════
Changelog:
  1. Added BASELINE_MODE env var to disable all AI calls
  2. compute_objective_score now also outputs mismatch reasons
  3. compute_personality_score considers only personality/interests/MBTI/zodiac;
     explicitly excludes lifestyle habits; missing info is called out and penalized
  4. (Frontend) Diet habit tag display + expanded card no longer overflows screen

Default weights:
  objective_score       Objective info       30%
  habits_score          Lifestyle habits     40%
  personality_score     Personality+interests 30%
══════════════════════════════════════════════════════════
"""

import os
import json
import asyncio
from openai import OpenAI
from database import UserProfile

# ── Baseline mode switch ──────────────────────────────────
# Set BASELINE_MODE=true in Railway Variables to enable.
# When false (default), the system uses normal AI mode.
BASELINE_MODE = os.getenv("BASELINE_MODE", "false").lower() == "true"

# ── Qwen client ───────────────────────────────────────────
qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
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
    """Synchronously call Qwen, return parsed dict; return {} on failure."""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ DASHSCOPE_API_KEY not set")
        return {}
    try:
        resp = qwen_client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"❌ JSON parse failed, raw: {text[:200]}")
            return {}
    except Exception as e:
        print(f"❌ Qwen call failed: {type(e).__name__}: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# Dimension 1: Objective info
# ══════════════════════════════════════════════════════════
async def compute_objective_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    """
    Structured rules (95-point cap) + lightweight bio AI (+5).
    Also outputs mismatch reasons.
    """
    has_data = any([
        me.school, me.major, me.study_country, me.study_state,
        me.city, me.budget_max, me.nationality, me.native_language,
    ])
    if not has_data:
        return None, None

    score = 0.0
    match_reasons = []     # matching points
    mismatch_reasons = []  # mismatching points

    # ── Study country +14.25 ─────────────────────────────
    if me.study_country and other.study_country:
        if me.study_country.strip().lower() == other.study_country.strip().lower():
            score += 14.25
            match_reasons.append(f"同在{me.study_country}留学")
        else:
            mismatch_reasons.append(f"留学国家不同（{me.study_country} vs {other.study_country}）")
    elif me.study_country and not other.study_country:
        mismatch_reasons.append("对方未填写留学国家")

    # ── Campus / state +14.25 ────────────────────────────
    if me.study_state and other.study_state:
        if me.study_state.strip().lower() == other.study_state.strip().lower():
            score += 14.25
            match_reasons.append(f"同在{me.study_state}")
        else:
            mismatch_reasons.append(f"校区/州不同（{me.study_state} vs {other.study_state}）")

    # ── City +14.25 ──────────────────────────────────────
    if me.city and other.city:
        if me.city.strip().lower() == other.city.strip().lower():
            score += 14.25
            match_reasons.append(f"同城市{me.city}")
        else:
            # Same country but different city — note this explicitly
            same_country = (
                me.study_country and other.study_country and
                me.study_country.strip().lower() == other.study_country.strip().lower()
            )
            if same_country:
                mismatch_reasons.append(f"同在{me.study_country}但城市不同（{me.city} vs {other.city}）")
            else:
                mismatch_reasons.append(f"城市不同（{me.city} vs {other.city}）")

    # ── Native language +14.25 ───────────────────────────
    if me.native_language and other.native_language:
        if me.native_language.strip().lower() == other.native_language.strip().lower():
            score += 14.25
            match_reasons.append(f"母语相同（{me.native_language}）")
        else:
            mismatch_reasons.append(f"母语不同（{me.native_language} vs {other.native_language}）")

    # ── School +9.5 ──────────────────────────────────────
    if me.school and other.school:
        if me.school.strip().lower() == other.school.strip().lower():
            score += 9.5
            match_reasons.append(f"同校（{me.school}）")
        else:
            mismatch_reasons.append(f"学校不同（{me.school} vs {other.school}）")

    # ── Major +4.75 ──────────────────────────────────────
    if me.major and other.major:
        if me.major.strip().lower() == other.major.strip().lower():
            score += 4.75
            match_reasons.append(f"同专业（{me.major}）")
        else:
            mismatch_reasons.append(f"专业不同（{me.major} vs {other.major}）")

    # ── Nationality +4.75 ────────────────────────────────
    if me.nationality and other.nationality:
        if me.nationality.strip().lower() == other.nationality.strip().lower():
            score += 4.75
            match_reasons.append(f"同国籍（{me.nationality}）")

    # ── Budget, max +19 ──────────────────────────────────
    my_max  = me.budget_max  or 0
    oth_max = other.budget_max or 0
    if my_max > 0 and oth_max > 0:
        diff_pct = abs(my_max - oth_max) / max(my_max, oth_max) * 100
        budget_score = max(0, 19 - diff_pct * 0.95)
        score += budget_score
        if budget_score >= 18:
            match_reasons.append("预算高度接近")
        elif budget_score >= 10:
            match_reasons.append("预算相近")
        else:
            mismatch_reasons.append(f"预算差距较大（{me.budget_max} vs {oth_max} {me.budget_currency or ''}）")

    # ── Bio shared traits, max +5 (lightweight AI) ───────
    bio_score = 0
    if me.bio and other.bio and not BASELINE_MODE:
        # System prompt — kept in Chinese to match the model's training distribution.
        # English translation:
        # "You are an information extraction assistant. Compare the two personal
        #  introductions and find shared OBJECTIVE traits, limited to: same
        #  hometown city, same hometown province, same undergraduate institution,
        #  same undergraduate major, same relationship status (single / in a
        #  relationship). Each shared trait scores 1 point, max 5. Zero traits
        #  found = 0. Do not deduct for mismatches.
        #  Output JSON only:
        #  {'score': 2, 'matches': ['both from Guangdong', 'both single']}"
        bio_prompt = (
            "你是一个信息提取助手。请对比以下两段个人介绍，"
            "找出客观信息上的共同点（仅限：老家同城市、老家同省份、"
            "本科院校相同、本科专业相同、情感状态相同，如单身/恋爱中）。"
            "每找到一个共同点得1分，最多5分。"
            "找不到共同点得0分。不一致的地方不扣分。\n\n"
            f"A的介绍：{me.bio}\n"
            f"B的介绍：{other.bio}\n\n"
            "只输出JSON，不输出任何其他内容：\n"
            '{"score": 2, "matches": ["老家同为广东", "都是单身"]}'
        )
        data = await asyncio.to_thread(_call_qwen, bio_prompt)
        if data:
            bio_score = min(int(data.get("score", 0)), 5)
            matches = data.get("matches", [])
            if matches:
                match_reasons.append("、".join(matches))

    score += bio_score
    final = min(round(score), 100)

    # Compose reason string: matches first, then mismatches
    reason_parts = []
    if match_reasons:
        reason_parts.append("✅ " + "；".join(match_reasons))
    if mismatch_reasons:
        reason_parts.append("❌ " + "；".join(mismatch_reasons))
    reason_str = "\n".join(reason_parts) if reason_parts else None

    return float(final), reason_str


# ══════════════════════════════════════════════════════════
# Dimension 2: Lifestyle habits
# ══════════════════════════════════════════════════════════
async def compute_habits_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    has_data = any([me.sleep_habit, me.diet_habit, me.habits, me.bio])
    if not has_data:
        return None, None

    # ── BASELINE MODE: pure rules, no AI ─────────────────
    if BASELINE_MODE:
        score = 0.0
        if me.sleep_habit and other.sleep_habit:
            if me.sleep_habit == other.sleep_habit:
                score += 50
            elif "flexible" in (me.sleep_habit, other.sleep_habit):
                score += 25
        my_h  = set(str_to_list(me.habits  or ""))
        oth_h = set(str_to_list(other.habits or ""))
        common = my_h & oth_h
        score += min(len(common) * 10, 50)
        return min(score, 100.0), "（Baseline模式：纯规则匹配）"

    my_habits  = str_to_list(me.habits  or "")
    oth_habits = str_to_list(other.habits or "")

    # System prompt — kept in Chinese.
    # English translation:
    # "You are an expert at matching international-student roommates. Given the
    #  lifestyle info of two students, evaluate their compatibility as roommates.
    #  Dimensions (high to low importance):
    #   1. Sleep schedule (early/late) — most impactful conflict source
    #   2. Lifestyle tags (smoking, pets, cleanliness) — large deduction on conflict
    #   3. Diet (eat together / separately / takeout) — large deduction on mismatch
    #   4. Lifestyle descriptions in the bio (sleep, hygiene, pets, guests, etc.)
    #  Hard rules:
    #   - smoker vs non-smoker     → severe conflict (-30+)
    #   - pet vs no-pet            → severe conflict (-25+)
    #   - very clean vs not-clean  → severe conflict (-20+)
    #   - sleep schedule differs by 3+ hours → clear conflict (-15+)
    #  Score 0-100, near 100 if highly similar with no conflicts, near 0 if severe.
    #  Output JSON only: {'score': 75, 'reason': 'one sentence summary'}"
    prompt = f"""你是留学生舍友匹配专家。请根据以下两位同学的生活习惯信息，评估他们作为舍友的生活习惯契合程度。

评估维度（重要性从高到低）：
1. 作息时间（早睡早起 vs 晚睡晚起）——冲突最影响同住体验
2. 生活习惯标签（抽烟/不抽烟、有宠物/不接受宠物、整洁程度）——有冲突大幅扣分
3. 饮食习惯（一起吃/各自解决/外卖）——如果一个一起吃，一个分开吃则大幅扣分
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
# Dimension 3: Personality + interests
# (Only personality / interests / MBTI / zodiac — NOT lifestyle habits)
# ══════════════════════════════════════════════════════════
async def compute_personality_score(
    me: UserProfile, other: UserProfile
) -> tuple[float | None, str | None]:
    has_data = any([me.mbti, me.zodiac, me.bio])
    if not has_data:
        return None, None

    # ── BASELINE MODE: only exact MBTI match ─────────────
    if BASELINE_MODE:
        score = 50.0  # neutral score when AI is off
        if me.mbti and other.mbti:
            score = 80.0 if me.mbti == other.mbti else 50.0
        return score, "（Baseline模式：仅MBTI精确匹配）"

    # Pre-check missing info; surface it inside the prompt
    missing_me    = [f for f, v in [("MBTI", me.mbti), ("星座", me.zodiac)] if not v]
    missing_other = [f for f, v in [("MBTI", other.mbti), ("星座", other.zodiac)] if not v]
    missing_note  = ""
    if missing_me:
        missing_note += f"注意：A未填写{'/'.join(missing_me)}。"
    if missing_other:
        missing_note += f"注意：B未填写{'/'.join(missing_other)}。"

    # System prompt — kept in Chinese.
    # English translation:
    # "You are an expert at matching international-student roommates, familiar
    #  with established MBTI compatibility research and zodiac personality
    #  analysis. Evaluate the personality + interests compatibility of two
    #  students.
    #  Important constraints:
    #   - This dimension ONLY evaluates personality, interests, MBTI, zodiac
    #   - Do NOT consider sleep, hygiene, diet, pets, or other lifestyle habits
    #     (those belong to a separate dimension)
    #   - From the bios, extract only personality and interest content; ignore
    #     lifestyle-related content
    #  Dimensions:
    #   1. MBTI compatibility (based on established research)
    #   2. Zodiac compatibility (holistic, not mechanical)
    #   3. Personality (extrovert/introvert/etc.) and interests in the bio
    #  Missing-info penalty: each missing key field (MBTI or zodiac) reduces
    #  available context; deduct 5-10 points accordingly. Users with more
    #  complete profiles should rank higher when other factors are similar.
    #  If anything is missing, mention it in the reason field.
    #  Score brackets:
    #   - 85+   : highly complementary + complete info + shared interests
    #   - 65-85 : broadly compatible
    #   - 50-65 : average, no major conflicts or alignments
    #   - 30-50 : clear conflict, or severely incomplete info
    #   - <30   : severe conflict
    #  Use the full 0-100 range.
    #  Output JSON: {'score': 72, 'reason': 'one sentence; mention missing info'}"
    prompt = f"""你是留学生舍友匹配专家，熟悉权威的MBTI兼容性研究和星座性格分析。
请综合评估以下两位同学的性格与兴趣爱好契合程度。

⚠️ 重要限制：
- 本维度【仅】评估性格、兴趣爱好、MBTI、星座
- 【不要】考虑作息、卫生、饮食、宠物等生活习惯（那是另一个维度的事）
- 个人介绍中只提取性格描述和兴趣爱好部分，忽略生活习惯相关内容

评估维度：
1. MBTI性格类型兼容性（基于权威MBTI配对研究）
2. 星座性格兼容性（综合判断，不要机械对应）
3. 个人介绍中关于性格（外向/内向/随和/独立等）和兴趣爱好的描述

缺失信息扣分规则：
{missing_note if missing_note else "双方信息完整。"}
- 每缺少一项关键信息（MBTI或星座），该维度可参考信息减少，酌情扣5-10分
- 信息填写越完整的用户，在条件相近时应获得更高分
- 如有缺失，在reason中明确说明"对方XX信息缺失"

A的性格兴趣：
- MBTI：{me.mbti or '未填写'}
- 星座：{me.zodiac or '未填写'}
- 个人介绍（仅性格兴趣部分）：{me.bio or '未填写'}

B的性格兴趣：
- MBTI：{other.mbti or '未填写'}
- 星座：{other.zodiac or '未填写'}
- 个人介绍（仅性格兴趣部分）：{other.bio or '未填写'}

评分标准：
- 85+：MBTI高度互补 + 星座相合 + 兴趣共鸣，信息完整
- 65-85：大体兼容，有部分共同点
- 50-65：一般，无明显冲突也无特别契合
- 30-50：有明显性格/兴趣冲突，或信息严重缺失
- 30以下：严重冲突
- 必须使用0-100完整区间，不要集中在60-80

只输出JSON：{{"score": 72, "reason": "一句话，如有缺失信息请注明"}}
不输出任何其他内容。"""

    data = await asyncio.to_thread(_call_qwen, prompt)
    if not data:
        return 50.0, None
    return float(data.get("score", 50)), data.get("reason")


# ══════════════════════════════════════════════════════════
# Skills label (display only, not scored)
# ══════════════════════════════════════════════════════════
def compute_skills_label(me: UserProfile, other: UserProfile) -> str | None:
    """Return "相同" (Same) / "互补" (Complementary) / None"""
    my_skills  = set(s.strip().lower() for s in str_to_list(me.special_skills  or ""))
    oth_skills = set(s.strip().lower() for s in str_to_list(other.special_skills or ""))
    if not my_skills and not oth_skills:
        return None
    return "相同" if my_skills & oth_skills else "互补"


# ══════════════════════════════════════════════════════════
# Weight resolution + total score
# ══════════════════════════════════════════════════════════
def resolve_weights(
    objective_score:   float | None,
    habits_score:      float | None,
    personality_score: float | None,
    custom_weights:    dict | None = None,
) -> dict[str, float]:
    """Compute final weights.

    If a dimension has no data (None), it gets MIN_WEIGHT (5%) and the
    remaining weight is redistributed proportionally among present dimensions.
    """
    base = custom_weights if custom_weights else dict(DEFAULT_WEIGHTS)
    missing = []
    if objective_score   is None: missing.append("objective")
    if habits_score      is None: missing.append("habits")
    if personality_score is None: missing.append("personality")

    if not missing:
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
    """Return (total 0-100, weights actually used)."""
    w = resolve_weights(objective_score, habits_score, personality_score, custom_weights)
    o = objective_score   if objective_score   is not None else 50.0
    h = habits_score      if habits_score      is not None else 50.0
    p = personality_score if personality_score is not None else 50.0
    total = o * w["objective"] + h * w["habits"] + p * w["personality"]
    return round(min(total, 100.0), 1), w
