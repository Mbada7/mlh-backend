from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from pydantic import BaseModel
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_active_user, create_access_token, verify_password
from app.models.user import User, UserRole
from app.models.video import Video

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(current_user: User = Depends(get_current_active_user)):
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class AdminLoginRequest(BaseModel):
    email: str
    password: str


# ─── Admin login (separate endpoint with extra validation) ────────────────────
@router.post("/login", response_model=dict)
async def admin_login(data: AdminLoginRequest, db: Session = Depends(get_db)):
    """Admin-specific login with role validation and encrypted response"""
    # Input validation
    if not data.email or not data.password:
        raise HTTPException(status_code=400, detail="Email and password required")

    if "@" not in data.email:
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Find user
    user = db.query(User).filter(User.email == data.email.lower().strip()).first()

    # Generic error to prevent user enumeration
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")

    role = user.role.value if hasattr(user.role, 'value') else str(user.role)
    if role != "admin":
        raise HTTPException(status_code=403, detail="This login is restricted to administrators")

    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(data={"sub": str(user.id), "role": role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": role,
        }
    }


@router.get("/dashboard", response_model=dict)
async def admin_dashboard(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin dashboard statistics"""
    total_users = db.query(func.count(User.id)).scalar()
    total_students = db.query(func.count(User.id)).filter(User.role == UserRole.STUDENT).scalar()
    total_lecturers = db.query(func.count(User.id)).filter(User.role == UserRole.LECTURER).scalar()
    total_videos = db.query(func.count(Video.id)).scalar()
    pending_videos = db.query(func.count(Video.id)).filter(Video.approval_status == "pending").scalar()
    total_views = db.query(func.sum(Video.view_count)).scalar() or 0
    total_likes = db.query(func.sum(Video.like_count)).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "students": total_students,
            "lecturers": total_lecturers,
            "admins": total_users - total_students - total_lecturers,
        },
        "videos": {
            "total": total_videos,
            "pending": pending_videos,
            "published": total_videos - pending_videos,
        },
        "engagement": {
            "total_views": total_views,
            "total_likes": total_likes,
        }
    }


@router.get("/users", response_model=List[dict])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    role: str = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all users (admin only)"""
    query = db.query(User)
    if role:
        try:
            query = query.filter(User.role == UserRole(role))
        except ValueError:
            pass

    users = query.offset(skip).limit(limit).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, 'value') else str(u.role),
            "department": u.department,
            "is_active": u.is_active,
            "is_verified": u.is_verified,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/toggle-active", response_model=dict)
async def toggle_user_active(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Activate or deactivate a user account"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user.is_active = not user.is_active
    db.commit()
    return {"message": f"User {'activated' if user.is_active else 'deactivated'}", "is_active": user.is_active}


@router.patch("/users/{user_id}/role", response_model=dict)
async def change_user_role(
    user_id: int,
    new_role: str = Query(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Change a user's role"""
    try:
        role_enum = UserRole(new_role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be: student, lecturer, admin")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role_enum
    db.commit()
    return {"message": f"Role updated to {new_role}", "user_id": user_id, "role": new_role}


@router.get("/videos/pending", response_model=List[dict])
async def admin_pending_videos(
    skip: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all pending videos for approval"""
    videos = db.query(Video).filter(
        Video.approval_status == "pending"
    ).offset(skip).limit(limit).all()

    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')

    return [
        {
            "id": v.id,
            "title": v.title,
            "uploader_id": v.uploaded_by_user_id,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{v.id}" if v.thumbnail_url else None,
        }
        for v in videos
    ]
