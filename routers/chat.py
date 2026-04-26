from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func
from typing import List, Dict
from database import get_db, User, UserProfile, Message
from schemas import MessageSend, MessageResponse, ShareContact, ConversationSummary
from auth_utils import get_current_user
from jose import jwt
import os

router = APIRouter()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production-min-32-chars")
ALGORITHM = "HS256"

# 内存中维护在线WebSocket连接 {user_id: WebSocket}
active_connections: Dict[str, WebSocket] = {}

@router.post("/send", response_model=MessageResponse)
async def send_message(
    body: MessageSend,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    msg = Message(
        sender_id=current_user.id,
        receiver_id=body.receiver_id,
        content=body.content
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # 如果对方在线，通过WebSocket实时推送
    target_ws = active_connections.get(str(body.receiver_id))
    if target_ws:
        try:
            await target_ws.send_json({
                "type": "new_message",
                "from": str(current_user.id),
                "content": body.content,
                "message_id": str(msg.id),
            })
        except Exception:
            pass

    return msg

@router.get("/history/{partner_id}", response_model=List[MessageResponse])
async def get_history(
    partner_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    result = await db.execute(
        select(Message).where(
            or_(
                and_(Message.sender_id == current_user.id, Message.receiver_id == partner_id),
                and_(Message.sender_id == partner_id, Message.receiver_id == current_user.id)
            )
        ).order_by(Message.created_at.asc()).offset(skip).limit(limit)
    )
    messages = result.scalars().all()

    # 标记已读
    for m in messages:
        if str(m.receiver_id) == str(current_user.id) and not m.is_read:
            m.is_read = True
    await db.commit()

    return messages

@router.get("/conversations", response_model=List[ConversationSummary])
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取所有会话列表（最后一条消息预览）"""
    # 找到所有与我有过消息的用户
    sent = await db.execute(
        select(Message.receiver_id).where(Message.sender_id == current_user.id).distinct()
    )
    received = await db.execute(
        select(Message.sender_id).where(Message.receiver_id == current_user.id).distinct()
    )
    partner_ids = set(
        [str(r[0]) for r in sent.fetchall()] +
        [str(r[0]) for r in received.fetchall()]
    )

    conversations = []
    for pid in partner_ids:
        # 最后一条消息
        last_msg_result = await db.execute(
            select(Message).where(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == pid),
                    and_(Message.sender_id == pid, Message.receiver_id == current_user.id)
                )
            ).order_by(Message.created_at.desc()).limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()
        if not last_msg:
            continue

        # 未读数
        unread_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.sender_id == pid,
                Message.receiver_id == current_user.id,
                Message.is_read == False
            )
        )
        unread = unread_result.scalar() or 0

        # 对方profile
        profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == pid))
        partner_profile = profile_result.scalar_one_or_none()

        conversations.append(ConversationSummary(
            partner_id=pid,
            partner_name=partner_profile.name if partner_profile else "未知用户",
            partner_avatar=partner_profile.avatar_url if partner_profile else None,
            last_message=last_msg.content[:50],
            last_message_time=last_msg.created_at,
            unread_count=unread,
        ))

    conversations.sort(key=lambda x: x.last_message_time, reverse=True)
    return conversations

@router.post("/share-contact")
async def share_contact(
    body: ShareContact,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """发送联系方式（微信/WhatsApp）"""
    content = f"[联系方式] {body.contact_type}: {body.contact_value}"
    msg = Message(
        sender_id=current_user.id,
        receiver_id=body.receiver_id,
        content=content,
        contact_type=body.contact_type,
        contact_value=body.contact_value
    )
    db.add(msg)
    await db.commit()
    return {"status": "ok"}

@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    """WebSocket实时聊天连接"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except Exception:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_connections[user_id] = websocket

    try:
        while True:
            data = await websocket.receive_json()
            # 客户端发消息格式: {"to": "receiver_uuid", "content": "hello"}
            if data.get("type") == "message":
                receiver_id = data.get("to")
                content = data.get("content", "")
                if receiver_id and content:
                    msg = Message(sender_id=user_id, receiver_id=receiver_id, content=content)
                    db.add(msg)
                    await db.commit()
                    # 推送给接收方
                    target_ws = active_connections.get(receiver_id)
                    if target_ws:
                        await target_ws.send_json({
                            "type": "new_message",
                            "from": user_id,
                            "content": content,
                        })
    except WebSocketDisconnect:
        active_connections.pop(user_id, None)
