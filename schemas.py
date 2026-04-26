from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

# ─── Auth ───────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=100)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str

# ─── Profile ────────────────────────────────────────────
class ProfileCreate(BaseModel):
    name: str
    gender: str                    # male / female / other
    school: str
    city: str
    avatar_url: Optional[str] = None

    zodiac: Optional[str] = None
    mbti: Optional[str] = None

    sleep_habit: str               # early / late / flexible
    diet_habit: str                # together / separate
    food_preference: Optional[str] = None  # sichuan / jiangzhehu / guangdong / north

    budget_min: int
    budget_max: int
    roommate_experience: int = Field(default=0, ge=0, le=5)

    special_skills: Optional[List[str]] = []   # ["kill_bug","barista",...]
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
    gender: str
    zodiac: Optional[str]
    mbti: Optional[str]
    sleep_habit: str
    diet_habit: str
    food_preference: Optional[str]
    budget_min: int
    budget_max: int
    roommate_experience: int
    special_skills: Optional[List[str]]
    bio: Optional[str]
    avatar_url: Optional[str]

    rule_score: float
    ai_score: float
    personality_score: float
    total_score: float

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
    contact_type: str    # wechat / whatsapp
    contact_value: str

class ConversationSummary(BaseModel):
    partner_id: UUID
    partner_name: str
    partner_avatar: Optional[str]
    last_message: str
    last_message_time: datetime
    unread_count: int
