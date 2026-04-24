# app/api/v1/notifications.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _serialize(n) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "video_id": n.video_id,
        "course_id": n.course_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/")
async def get_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get current user's notifications"""
    svc = NotificationService(db)
    notifications = svc.get_user_notifications(current_user.id, skip, limit, unread_only)
    return [_serialize(n) for n in notifications]


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get count of unread notifications"""
    svc = NotificationService(db)
    return {"count": svc.get_unread_count(current_user.id)}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Mark a single notification as read"""
    svc = NotificationService(db)
    svc.mark_read(notification_id, current_user.id)
    return {"status": "ok"}


@router.post("/mark-all-read")
async def mark_all_read(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read"""
    svc = NotificationService(db)
    svc.mark_all_read(current_user.id)
    return {"status": "ok"}
