from pydantic import BaseModel, EmailStr, Field, validator
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

    # ── 旧字段（保留兼容，前端旧代码不会报错）──
    rule_score:        float = 0.0
    ai_score:          float = 0.0
    personality_score: float = 0.0
    total_score:       float = 0.0

    # ── 新增：5维度独立分数（0-100）──
    habits_score:      float = 0.0   # 生活习惯
    objective_score:   float = 0.0   # 客观信息
    skills_score:      float = 0.0   # 技能
    interest_score:    float = 0.0   # 兴趣爱好
    # personality_score 复用旧字段，不重复

    # ── 新增：实际使用的权重（0-1小数，供前端展示）──
    score_weights: Optional[Dict[str, float]] = None

    match_reason: Optional[str] = None

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
