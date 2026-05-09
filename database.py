from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/roommate_db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"server_settings": {"application_name": "roommate"}},
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sent_messages = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    received_messages = relationship("Message", foreign_keys="Message.receiver_id", back_populates="receiver")

class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)

    # 基本信息 basic info
    name = Column(String(100), nullable=False)
    gender = Column(String(10), nullable=False)
    nationality = Column(String(100), nullable=True)
    study_country = Column(String(100), nullable=True)
    study_state = Column(String(100), nullable=True)
    city = Column(String(100), nullable=False)
    native_language = Column(String(50), nullable=True)
    school = Column(String(200), nullable=False)
    degree = Column(String(20), nullable=True)
    major = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)

    # 性格标签 personality tag
    zodiac = Column(String(20), nullable=True)
    mbti = Column(String(10), nullable=True)

    # 生活习惯 habit (lifestyle)
    sleep_habit = Column(String(20), nullable=False)
    diet_habit = Column(String(20), nullable=False)
    food_preference = Column(String(50), nullable=True)
    habits = Column(String(500), nullable=True)

    # 租房 (renting)
    budget_currency = Column(String(10), nullable=True)
    budget_max = Column(Integer, nullable=True)
    budget_min = Column(Integer, nullable=True)
    room_types = Column(String(100), nullable=True)

    # 经历 (roommate experience)
    roommate_experience = Column(Integer, default=0)

    # 特殊技能 speicla abilities
    special_skills = Column(String(200), nullable=True)

    # 自我介绍 self-intro
    bio = Column(Text, nullable=True)
    profile_summary = Column(Text, nullable=True)

    # ── 新增：档案可查询状态 added: profile status ──────────────────────────────
    # True = 正常出现在匹配搜索中（默认）
    # False = 撤销档案，不出现在搜索中，但内容保留
    is_searchable = Column(Boolean, default=True, nullable=False)

    # ── 新增：评分版本号（用于缓存失效）added: cache and new matching rule test ──────────────────
    # 每次 profile 更新时 +1，matching 检测到版本不同则重算 +1 each time
    profile_version = Column(Integer, default=1, nullable=False)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="profile")


class MatchScore(Base):
    __tablename__ = "match_scores"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id          = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_user_id   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    
    rule_score        = Column(Float, default=0.0)
    ai_score          = Column(Float, default=0.0)
    personality_score = Column(Float, default=0.0)
    total_score       = Column(Float, default=0.0)
    match_reason      = Column(Text, nullable=True)

    # scoring
    habits_score      = Column(Float, default=0.0)
    objective_score   = Column(Float, default=0.0)
    skills_score      = Column(Float, default=0.0)
    interest_score    = Column(Float, default=0.0)
    score_weights     = Column(Text, nullable=True)

    # comments and reasons
    objective_reason   = Column(Text, nullable=True)
    habits_reason      = Column(Text, nullable=True)
    personality_reason = Column(Text, nullable=True)
    skills_label       = Column(String(20), nullable=True)

    # ── added: profile_version ────────────
    # format："v{user_version}_{target_version}"，如 "v2_3"
    score_version      = Column(String(20), nullable=True)

    computed_at       = Column(DateTime, default=datetime.utcnow)


class RoommateMatch(Base):
    """lock roommate table """
    __tablename__ = "roommate_matches"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    receiver_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # pending / accepted / rejected / considering
    status         = Column(String(20), default="pending", nullable=False)

    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    receiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)
    contact_type = Column(String(20), nullable=True)
    contact_value = Column(String(100), nullable=True)

    # ── added: invite ─────────────
    # "text" | "roommate_invite" | "roommate_response"
    message_type   = Column(String(30), default="text", nullable=False)
    # invite data
    message_meta   = Column(Text, nullable=True)

    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
