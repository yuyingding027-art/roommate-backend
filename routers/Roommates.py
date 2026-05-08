"""
锁定舍友路由
POST   /api/roommates/invite          发起锁定邀请（自动发送邀请消息到 chat）
POST   /api/roommates/respond         回应邀请（同意/拒绝/考虑一下）
GET    /api/roommates/locked          获取当前用户已锁定的舍友列表 + 数量
GET    /api/roommates/pending         获取收到的待处理邀请
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List
import json
from database import get_db, User, UserProfile, RoommateMatch, Message
from schemas import (
    RoommateInviteRequest, RoommateInviteResponse,
    RoommateRespondRequest, RoommateMatchInfo, LockedRoommatesResponse,
)
from auth_utils import get_current_user
from datetime import datetime
import uuid

router = APIRouter()


async def _get_profile(db: AsyncSession, user_id) -> UserProfile | None:
    r = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    return r.scalar_one_or_none()


def _profile_to_meta(profile: UserProfile, email: str = None) -> dict:
    """把 profile 序列化成邀请卡片用的 meta"""
    def sl(s): return [x for x in s.split(",") if x] if s else []
    return {
        "name":               profile.name,
        "gender":             profile.gender,
        "school":             profile.school,
        "major":              profile.major,
        "city":               profile.city,
        "study_country":      profile.study_country,
        "study_state":        profile.study_state,
        "native_language":    profile.native_language,
        "nationality":        profile.nationality,
        "zodiac":             profile.zodiac,
        "mbti":               profile.mbti,
        "sleep_habit":        profile.sleep_habit,
        "diet_habit":         profile.diet_habit,
        "food_preference":    profile.food_preference,
        "habits":             sl(profile.habits or ""),
        "budget_max":         profile.budget_max,
        "budget_currency":    profile.budget_currency,
        "room_types":         sl(profile.room_types or ""),
        "special_skills":     sl(profile.special_skills or ""),
        "bio":                profile.bio,
        "avatar_url":         profile.avatar_url,
        "roommate_experience":profile.roommate_experience,
        "email":              email,
    }


@router.post("/invite", response_model=RoommateInviteResponse)
async def invite_roommate(
    body: RoommateInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    发起锁定舍友邀请：
    1. 创建 RoommateMatch 记录（status=pending）
    2. 自动发送一条 message_type=roommate_invite 的消息到 chat
    """
    if body.receiver_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能邀请自己")

    # 检查是否已有进行中的邀请
    existing = await db.execute(
        select(RoommateMatch).where(
            or_(
                and_(
                    RoommateMatch.requester_id == current_user.id,
                    RoommateMatch.receiver_id  == body.receiver_id,
                ),
                and_(
                    RoommateMatch.requester_id == body.receiver_id,
                    RoommateMatch.receiver_id  == current_user.id,
                ),
            ),
            RoommateMatch.status.in_(["pending", "accepted"]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="已存在进行中的邀请或已锁定")

    # 创建锁定关系
    invite = RoommateMatch(
        requester_id=current_user.id,
        receiver_id=body.receiver_id,
        status="pending",
    )
    db.add(invite)

    # 获取当前用户 profile，打包进邀请卡片消息
    my_profile = await _get_profile(db, current_user.id)
    meta = {
        "invite_id": str(invite.id),
        "profile":   _profile_to_meta(my_profile, email=current_user.email) if my_profile else {},
    }

    # 发送邀请消息到 chat
    msg = Message(
        sender_id    = current_user.id,
        receiver_id  = body.receiver_id,
        content      = "发送了一个锁定舍友邀请",
        message_type = "roommate_invite",
        message_meta = json.dumps(meta),
        is_read      = False,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(invite)

    return RoommateInviteResponse(invite_id=invite.id, status=invite.status)


@router.post("/respond")
async def respond_to_invite(
    body: RoommateRespondRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    回应邀请：accepted / rejected / considering
    - accepted：双方锁定数各+1，自动发送系统消息，询问是否撤销档案
    - rejected / considering：发送对应回应消息
    """
    if body.response not in ("accepted", "rejected", "considering"):
        raise HTTPException(status_code=400, detail="无效的回应类型")

    invite_r = await db.execute(
        select(RoommateMatch).where(
            RoommateMatch.id          == body.invite_id,
            RoommateMatch.receiver_id == current_user.id,
            RoommateMatch.status      == "pending",
        )
    )
    invite = invite_r.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请不存在或已处理")

    invite.status     = body.response
    invite.updated_at = datetime.utcnow()

    # 状态文字映射
    status_text = {
        "accepted":    "同意了锁定舍友邀请 🎉",
        "rejected":    "拒绝了锁定舍友邀请",
        "considering": "正在考虑锁定舍友邀请...",
    }[body.response]

    # 回应消息 → 发给 requester
    resp_meta = {
        "invite_id": str(invite.id),
        "response":  body.response,
    }
    resp_msg = Message(
        sender_id    = current_user.id,
        receiver_id  = invite.requester_id,
        content      = status_text,
        message_type = "roommate_response",
        message_meta = json.dumps(resp_meta),
        is_read      = False,
    )
    db.add(resp_msg)

    if body.response == "accepted":
        # 发系统消息给双方，询问是否撤销档案
        for uid, other_uid in [
            (invite.requester_id, current_user.id),
            (current_user.id, invite.requester_id),
        ]:
            system_msg = Message(
                sender_id    = uid,
                receiver_id  = uid,  # 发给自己 = 系统提示
                content      = "你已成功锁定一位舍友！是否需要撤销可查询档案？（撤销后其他用户将无法在匹配中看到你）",
                message_type = "system_archive_prompt",
                message_meta = json.dumps({"invite_id": str(invite.id)}),
                is_read      = False,
            )
            db.add(system_msg)

    await db.commit()
    return {"status": body.response, "message": status_text}


@router.get("/locked", response_model=LockedRoommatesResponse)
async def get_locked_roommates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户已锁定的舍友（双向 accepted）"""
    result = await db.execute(
        select(RoommateMatch).where(
            or_(
                RoommateMatch.requester_id == current_user.id,
                RoommateMatch.receiver_id  == current_user.id,
            ),
            RoommateMatch.status == "accepted",
        )
    )
    matches = result.scalars().all()

    roommates = []
    for m in matches:
        partner_id = m.receiver_id if m.requester_id == current_user.id else m.requester_id
        profile = await _get_profile(db, partner_id)
        roommates.append(RoommateMatchInfo(
            id           = m.id,
            partner_id   = partner_id,
            partner_name = profile.name if profile else "未知",
            partner_avatar = profile.avatar_url if profile else None,
            status       = m.status,
            created_at   = m.created_at,
        ))

    return LockedRoommatesResponse(count=len(roommates), roommates=roommates)


@router.get("/pending", response_model=list)
async def get_pending_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取收到的待处理邀请"""
    result = await db.execute(
        select(RoommateMatch).where(
            RoommateMatch.receiver_id == current_user.id,
            RoommateMatch.status      == "pending",
        )
    )
    invites = result.scalars().all()
    return [{"invite_id": str(i.id), "requester_id": str(i.requester_id), "created_at": i.created_at} for i in invites]
