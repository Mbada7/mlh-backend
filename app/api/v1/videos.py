# app/api/v1/videos.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from app.core.database import get_db
from app.core.security import get_current_active_user, get_current_user_optional
from app.models.user import User
from app.models.video import Video
from app.schemas.video import VideoResponse, CommentCreate, CommentResponse
from app.services.video_service import VideoService

router = APIRouter(prefix="/videos", tags=["Videos"])


@router.post("/upload", response_model=VideoResponse)
async def upload_video(
    title: str = Form(...),
    description: str = Form(None),
    course_id: Optional[int] = Form(None),
    tags: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Upload a new video"""
    tag_list = [t.strip() for t in tags.split(',')] if tags else []
    video_service = VideoService(db)
    video = video_service.upload_video(
        user_id=current_user.id,
        file=file,
        title=title,
        description=description,
        course_id=course_id,
        tags=tag_list,
        user_role=str(current_user.role.value) if hasattr(current_user.role, 'value') else str(current_user.role)
    )
    uploader = db.query(User).filter(User.id == video.uploaded_by_user_id).first()
    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')
    return {
        "id": video.id,
        "title": video.title,
        "description": video.description,
        "video_url": f"{base_url}/api/v1/videos/stream/{video.id}",
        "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
        "duration": video.duration,
        "view_count": video.view_count,
        "like_count": video.like_count,
        "comment_count": video.comment_count,
        "share_count": video.share_count,
        "course_id": video.course_id,
        "uploaded_by_user_id": video.uploaded_by_user_id,
        "uploader_name": uploader.full_name if uploader else "Unknown",
        "uploader_profile_picture": uploader.profile_picture if uploader else None,
        "tags": video.tags or [],
        "is_published": video.is_published,
        "is_featured": video.is_featured,
        "created_at": video.created_at
    }


@router.get("/pending", response_model=List[VideoResponse])
async def get_pending_videos(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get pending videos awaiting approval (lecturers see their course videos)"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role not in ["lecturer", "admin"]:
        raise HTTPException(status_code=403, detail="Lecturer or admin access required")

    video_service = VideoService(db)
    pending = video_service.get_pending_videos(current_user.id, skip, limit)

    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')
    result = []
    for video in pending:
        uploader = db.query(User).filter(User.id == video.uploaded_by_user_id).first()
        result.append({
            "id": video.id,
            "title": video.title,
            "description": video.description,
            "video_url": f"{base_url}/api/v1/videos/stream/{video.id}",
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
            "duration": video.duration,
            "view_count": video.view_count,
            "like_count": video.like_count,
            "comment_count": video.comment_count,
            "share_count": video.share_count,
            "course_id": video.course_id,
            "uploaded_by_user_id": video.uploaded_by_user_id,
            "uploader_name": uploader.full_name if uploader else "Unknown",
            "uploader_profile_picture": uploader.profile_picture if uploader else None,
            "tags": video.tags or [],
            "is_published": video.is_published,
            "is_featured": video.is_featured,
            "created_at": video.created_at,
        })
    return result


@router.get("/stream/{video_id}")
async def stream_video(
    video_id: int,
    db: Session = Depends(get_db)
):
    """Stream video file"""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or not os.path.exists(video.video_url):
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(
        path=video.video_url,
        media_type="video/mp4",
        filename=os.path.basename(video.video_url)
    )


@router.get("/thumbnail/{video_id}")
async def get_thumbnail(
    video_id: int,
    db: Session = Depends(get_db)
):
    """Get thumbnail image"""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or not video.thumbnail_url or not os.path.exists(video.thumbnail_url):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(
        path=video.thumbnail_url,
        media_type="image/jpeg"
    )


@router.get("/course/{course_id}", response_model=List[VideoResponse])
async def get_course_videos_by_id(
    course_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Get all published videos for a course"""
    videos = db.query(Video).filter(
        Video.course_id == course_id,
        Video.is_published
    ).order_by(Video.created_at.desc()).offset(skip).limit(limit).all()

    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')
    result = []
    for video in videos:
        uploader = db.query(User).filter(User.id == video.uploaded_by_user_id).first()
        result.append({
            "id": video.id,
            "title": video.title,
            "description": video.description,
            "video_url": f"{base_url}/api/v1/videos/stream/{video.id}",
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
            "duration": video.duration,
            "view_count": video.view_count,
            "like_count": video.like_count,
            "comment_count": video.comment_count,
            "share_count": video.share_count,
            "course_id": video.course_id,
            "uploaded_by_user_id": video.uploaded_by_user_id,
            "uploader_name": uploader.full_name if uploader else "Unknown",
            "uploader_profile_picture": uploader.profile_picture if uploader else None,
            "tags": video.tags or [],
            "is_published": video.is_published,
            "is_featured": video.is_featured,
            "created_at": video.created_at
        })
    return result


# ═══════════════════════════════════════════════════════════════
#  PARAMETERISED ROUTES  /{video_id} and sub-paths
# ═══════════════════════════════════════════════════════════════

@router.get("/{video_id}")
async def get_video(
    video_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Get video by ID.
    Published videos → everyone.
    Unpublished → uploader, course lecturer, or admin only.
    """
    video_service = VideoService(db)
    user_id = current_user.id if current_user else None
    user_role = (current_user.role.value
                 if current_user and hasattr(current_user.role, 'value')
                 else (str(current_user.role) if current_user else "student"))
    video_data = video_service.get_video_with_details(video_id, user_id, user_role)
    return video_data


@router.post("/{video_id}/approve")
async def approve_video(
    video_id: int,
    approved: bool,
    rejection_reason: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Approve or reject a student video (lecturer only)"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role not in ["lecturer", "admin"]:
        raise HTTPException(status_code=403, detail="Lecturer access required")
    video_service = VideoService(db)
    return video_service.approve_student_video(video_id, current_user.id, approved, rejection_reason)


@router.get("/{video_id}/progress")
async def get_watch_progress(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user's watch progress for a video"""
    from app.models.interaction import UserVideoInteraction
    watch = db.query(UserVideoInteraction).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.video_id == video_id,
        UserVideoInteraction.interaction_type == "view"
    ).first()
    if not watch:
        return {"video_id": video_id, "watch_percentage": 0.0,
                "watch_duration": 0, "last_watched": None, "completed": False}
    return {
        "video_id": video_id,
        "watch_percentage": watch.watch_percentage,
        "watch_duration": watch.watch_duration,
        "last_watched": watch.created_at,
        "completed": watch.watch_percentage >= 0.9
    }


@router.post("/{video_id}/watch-progress")
async def update_watch_progress(
    video_id: int,
    watch_percentage: float = 0.0,
    watch_duration: int = 0,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update user's watch progress for a video"""
    video_service = VideoService(db)
    return video_service.update_watch_progress(video_id, current_user.id, watch_percentage, watch_duration)


@router.post("/{video_id}/share")
async def share_video(
    video_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Increment share count"""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video.share_count += 1
    db.commit()
    return {"share_count": video.share_count}


@router.post("/{video_id}/report")
async def report_video(
    video_id: int,
    reason: str,
    details: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Report a video"""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    from app.models.interaction import UserVideoInteraction
    db.add(UserVideoInteraction(
        user_id=current_user.id,
        video_id=video_id,
        interaction_type="report"
    ))
    db.commit()
    return {"status": "reported", "reason": reason}


@router.put("/{video_id}")
async def update_video(
    video_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    is_published: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update video metadata"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    video_service = VideoService(db)
    video = video_service.update_video(
        video_id=video_id, user_id=current_user.id, user_role=role,
        title=title, description=description, tags=tags, is_published=is_published
    )
    uploader = db.query(User).filter(User.id == video.uploaded_by_user_id).first()
    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')
    return {
        "id": video.id, "title": video.title, "description": video.description,
        "video_url": f"{base_url}/api/v1/videos/stream/{video.id}",
        "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
        "duration": video.duration, "view_count": video.view_count, "like_count": video.like_count,
        "comment_count": video.comment_count, "share_count": video.share_count,
        "course_id": video.course_id, "uploaded_by_user_id": video.uploaded_by_user_id,
        "uploader_name": uploader.full_name if uploader else "Unknown",
        "uploader_profile_picture": uploader.profile_picture if uploader else None,
        "tags": video.tags or [], "is_published": video.is_published,
        "is_featured": video.is_featured, "created_at": video.created_at
    }


@router.delete("/{video_id}")
async def delete_video(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a video"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    video_service = VideoService(db)
    return video_service.delete_video(video_id, current_user.id, role)


@router.post("/{video_id}/like")
async def like_video(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Like or unlike a video"""
    video_service = VideoService(db)
    return video_service.like_video(video_id, current_user.id)


@router.post("/{video_id}/bookmark")
async def bookmark_video(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Bookmark or unbookmark a video"""
    video_service = VideoService(db)
    return video_service.bookmark_video(video_id, current_user.id)


@router.post("/{video_id}/comments", response_model=CommentResponse)
async def add_comment(
    video_id: int,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add comment to video"""
    video_service = VideoService(db)
    return video_service.add_comment(
        video_id=video_id, user_id=current_user.id,
        content=comment_data.content, parent_comment_id=comment_data.parent_comment_id
    )


@router.get("/{video_id}/comments", response_model=List[CommentResponse])
async def get_comments(
    video_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get comments for video"""
    video_service = VideoService(db)
    return video_service.get_comments(video_id, skip, limit)
