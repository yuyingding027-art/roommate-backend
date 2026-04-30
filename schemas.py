from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime

# ─── Auth ───────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=100)

class SendCodeRequest(BaseModel):
    email: EmailStr

class VerifyCodeRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=6, max_length=6)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str

# ─── Profile ────────────────────────────────────────────
class ProfileCreate(BaseModel):
    name: str
    gender: str
    nationality: Optional[str] = None
    study_country: Optional[str] = None
    study_state: Optional[str] = None
    city: str
    native_language: Optional[str] = None
    school: str
    degree: Optional[str] = None
    major: Optional[str] = None
    avatar_url: Optional[str] = None

    zodiac: Optional[str] = None
    mbti: Optional[str] = None

    sleep_habit: str
    diet_habit: str
    food_preference: Optional[str] = None
    habits: Optional[List[str]] = []

    budget_currency: Optional[str] = None
    budget_max: Optional[int] = None
    budget_min: Optional[int] = None
    room_types: Optional[List[str]] = []

    roommate_experience: int = Field(default=0, ge=0, le=5)
    special_skills: Optional[List[str]] = []
    bio: Optional[str] = None

class ProfileResponse(ProfileCreate):
    user_id: UUID
    email: Optional[str] = None
    profile_summary: Optional[str] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

# ─── Matching ────────────────────────────────────────────
class MatchResult(BaseModel):
    user_id: UUID
    name: str
    school: str
    city: str
    study_country: Optional[str]
    study_state: Optional[str]
    native_language: Optional[str]
    degree: Optional[str]
    major: Optional[str]
    gender: str
    zodiac: Optional[str]
    mbti: Optional[str]
    sleep_habit: str
    diet_habit: str
    food_preference: Optional[str]
    habits: Optional[List[str]]
    budget_currency: Optional[str]
    budget_max: Optional[int]
    budget_min: Optional[int]
    room_types: Optional[List[str]]
    roommate_experience: int
    special_skills: Optional[List[str]]
    bio: Optional[str]
    avatar_url: Optional[str]
    email: Optional[str] = None

    # ── 三维度分数 ──────────────────────────────────────
    total_score:       float = 0.0
    objective_score:   float = 0.0   # 客观信息 30%
    habits_score:      float = 0.0   # 生活习惯 40%
    personality_score: float = 0.0   # 性格兴趣 30%（原personality+interest合并）

    # ── 技能标签（不参与评分）──────────────────────────
    skills_label: Optional[str] = None  # "相同" | "互补" | None

    # ── 实际使用权重 ────────────────────────────────────
    score_weights: Optional[Dict[str, float]] = None

    # ── AI 评语 ─────────────────────────────────────────
    match_reason:        Optional[str] = None  # 综合评语
    objective_reason:    Optional[str] = None  # 客观维度说明
    habits_reason:       Optional[str] = None  # 习惯维度说明
    personality_reason:  Optional[str] = None  # 性格兴趣维度说明

    # ── 旧字段保留兼容（前端旧代码不报错）──────────────
    rule_score:    float = 0.0
    ai_score:      float = 0.0
    skills_score:  float = 0.0
    interest_score: float = 0.0
    match_points:   Optional[List[str]] = None
    mismatch_points: Optional[List[str]] = None

# ─── Chat ────────────────────────────────────────────────
class MessageSend(BaseModel):
    receiver_id: UUID
    content: str

class MessageResponse(BaseModel):
    id: UUID
    sender_id: UUID
    receiver_id: UUID
    content: str
    created_at: datetime
    is_read: bool
    model_config = {"from_attributes": True}

class ShareContact(BaseModel):
    receiver_id: UUID
    contact_type: str
    contact_value: str

class ConversationSummary(BaseModel):
    partner_id: UUID
    partner_name: str
    partner_avatar: Optional[str]
    last_message: str
    last_message_time: datetime
    unread_count: int
