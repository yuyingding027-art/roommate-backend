"""
Roommate Lock routes
POST   /api/roommates/invite          Send a lock invitation (automatically posts an invite card into chat)
POST   /api/roommates/respond         Respond to an invitation (accepted / rejected / considering)
GET    /api/roommates/locked          List all roommates the current user has locked + total count
GET    /api/roommates/pending         List pending invitations received by the current user
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
    """Serialize a profile into the meta dict embedded in an invite card."""
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
    Send a roommate-lock invitation:
    1. Create a RoommateMatch record (status=pending)
    2. Automatically post a message with message_type=roommate_invite into chat
    """
    if body.receiver_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能邀请自己")

    # Check whether there is already an active invitation
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

    # Create the lock relationship
    invite = RoommateMatch(
        requester_id=current_user.id,
        receiver_id=body.receiver_id,
        status="pending",
    )
    db.add(invite)

    # Fetch current user's profile and pack it into the invite card payload
    my_profile = await _get_profile(db, current_user.id)
    meta = {
        "invite_id": str(invite.id),
        "profile":   _profile_to_meta(my_profile, email=current_user.email) if my_profile else {},
    }

    # Post the invite message into chat
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
    Respond to an invite: accepted / rejected / considering
    - accepted: both users' locked-roommate count +1; system message asks each whether to hide their profile
    - rejected / considering: send the corresponding response message
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

    # Status → display text mapping (kept in Chinese for end users)
    status_text = {
        "accepted":    "同意了锁定舍友邀请 🎉",
        "rejected":    "拒绝了锁定舍友邀请",
        "considering": "正在考虑锁定舍友邀请...",
    }[body.response]

    # Response message → sent to the original requester
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
        # Send a system prompt to both users asking whether to hide their profile
        for uid, other_uid in [
            (invite.requester_id, current_user.id),
            (current_user.id, invite.requester_id),
        ]:
            system_msg = Message(
                sender_id    = uid,
                receiver_id  = uid,  # sender == receiver indicates a system prompt
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
    """List all roommates the current user has locked (status=accepted, either direction)."""
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
            partner_name = profile.name if profile else "Unknown",
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
    """List pending invitations received by the current user."""
    result = await db.execute(
        select(RoommateMatch).where(
            RoommateMatch.receiver_id == current_user.id,
            RoommateMatch.status      == "pending",
        )
    )
    invites = result.scalars().all()
    return [{"invite_id": str(i.id), "requester_id": str(i.requester_id), "created_at": i.created_at} for i in invites]
