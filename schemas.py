from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
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
    nationality: Optional[str] = None          # 国籍
    study_country: Optional[str] = None        # 留学国家
    study_state: Optional[str] = None          # 州/省
    city: str
    native_language: Optional[str] = None      # 母语
    school: str
    degree: Optional[str] = None               # bachelor/master/phd
    major: Optional[str] = None                # 专业
    avatar_url: Optional[str] = None

    zodiac: Optional[str] = None
    mbti: Optional[str] = None

    sleep_habit: str
    diet_habit: str
    food_preference: Optional[str] = None
    habits: Optional[List[str]] = []           # 生活习惯多选

    budget_currency: Optional[str] = None      # USD/CNY/GBP等
    budget_max: Optional[int] = None           # 最高预算
    budget_min: Optional[int] = None           # 兼容旧字段
    room_types: Optional[List[str]] = []       # 期待房型多选

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
    rule_score: float
    ai_score: float
    personality_score: float
    total_score: float
    match_reason: Optional[str] = None         # AI生成的匹配原因

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
