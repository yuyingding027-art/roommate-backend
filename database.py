from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
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

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)

    # 基本信息
    name = Column(String(100), nullable=False)
    gender = Column(String(10), nullable=False)  # male/female/other
    school = Column(String(200), nullable=False)
    city = Column(String(100), nullable=False)
    avatar_url = Column(String(500), nullable=True)

    # 性格标签
    zodiac = Column(String(20), nullable=True)   # 星座
    mbti = Column(String(10), nullable=True)      # MBTI

    # 生活习惯
    sleep_habit = Column(String(20), nullable=False)   # early/late/flexible
    diet_habit = Column(String(20), nullable=False)    # together/separate
    food_preference = Column(String(50), nullable=True) # sichuan/jiangzhehu/guangdong/north (仅together时)

    # 租房
    budget_min = Column(Integer, nullable=False)
    budget_max = Column(Integer, nullable=False)

    # 经历
    roommate_experience = Column(Integer, default=0)  # 0-5段

    # 特殊技能（存为逗号分隔字符串）
    special_skills = Column(String(200), nullable=True)  # kill_bug,strong,bartender,barista

    # 自我介绍 / Profile
    bio = Column(Text, nullable=True)

    # AI匹配用的embedding摘要（存Claude分析的文本）
    profile_summary = Column(Text, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="profile")

class MatchScore(Base):
    __tablename__ = "match_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rule_score = Column(Float, default=0.0)       # 规则匹配分 (0-100)
    ai_score = Column(Float, default=0.0)          # AI profile匹配分 (0-100)
    personality_score = Column(Float, default=0.0) # MBTI+星座匹配分 (0-100)
    total_score = Column(Float, default=0.0)       # 综合分
    computed_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    receiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

    # 用户选择分享联系方式
    contact_type = Column(String(20), nullable=True)   # wechat/whatsapp/null
    contact_value = Column(String(100), nullable=True)

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
