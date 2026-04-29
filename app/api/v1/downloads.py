from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta, timezone
import os

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.video import Video
from app.models.quiz import VideoDownload

router = APIRouter(prefix="/downloads", tags=["Downloads"])

DOWNLOAD_EXPIRY_DAYS = 7


@router.post("/{video_id}", response_model=dict)
async def record_download(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Record that a user has downloaded a video for offline viewing.
    Expiry is set to 7 days from download date."""
    video = db.query(Video).filter(Video.id == video_id, Video.is_published == True).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check for existing active download
    existing = db.query(VideoDownload).filter(
        VideoDownload.user_id == current_user.id,
        VideoDownload.video_id == video_id,
        VideoDownload.is_active == True
    ).first()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=DOWNLOAD_EXPIRY_DAYS)

    if existing:
        # Refresh expiry
        existing.downloaded_at = now
        existing.expires_at = expires_at
        db.commit()
        return {
            "message": "Download refreshed",
            "expires_at": expires_at.isoformat(),
            "days_remaining": DOWNLOAD_EXPIRY_DAYS
        }

    download = VideoDownload(
        user_id=current_user.id,
        video_id=video_id,
        expires_at=expires_at,
        file_path=video.video_url
    )
    db.add(download)
    db.commit()
    return {
        "message": "Download recorded",
        "expires_at": expires_at.isoformat(),
        "days_remaining": DOWNLOAD_EXPIRY_DAYS,
        "video_url": video.video_url
    }


@router.get("/my-downloads", response_model=List[dict])
async def get_my_downloads(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all downloaded videos for the current user with expiry status"""
    now = datetime.now(timezone.utc)

    downloads = db.query(VideoDownload).filter(
        VideoDownload.user_id == current_user.id,
        VideoDownload.is_active == True
    ).order_by(VideoDownload.downloaded_at.desc()).all()

    results = []
    for d in downloads:
        video = db.query(Video).filter(Video.id == d.video_id).first()
        if not video:
            continue

        expires_at = d.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        is_expired = now > expires_at
        days_remaining = max(0, (expires_at - now).days)

        # Auto-expire if past date
        if is_expired:
            d.is_active = False
            db.commit()
            continue

        from app.core.config import settings
        base_url = settings.BACKEND_URL.rstrip('/')

        results.append({
            "download_id": d.id,
            "video_id": d.video_id,
            "video_title": video.title,
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
            "duration": video.duration,
            "downloaded_at": d.downloaded_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "days_remaining": days_remaining,
            "is_expired": is_expired,
            "video_url": f"{base_url}/api/v1/videos/stream/{video.id}"
        })

    return results


@router.delete("/{video_id}", response_model=dict)
async def remove_download(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Remove a downloaded video"""
    download = db.query(VideoDownload).filter(
        VideoDownload.user_id == current_user.id,
        VideoDownload.video_id == video_id
    ).first()

    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    download.is_active = False
    db.commit()
    return {"message": "Download removed"}


@router.get("/check/{video_id}", response_model=dict)
async def check_download(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Check if a video is downloaded and not expired"""
    now = datetime.now(timezone.utc)
    download = db.query(VideoDownload).filter(
        VideoDownload.user_id == current_user.id,
        VideoDownload.video_id == video_id,
        VideoDownload.is_active == True
    ).first()

    if not download:
        return {"is_downloaded": False, "is_expired": False, "days_remaining": 0}

    expires_at = download.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    is_expired = now > expires_at
    days_remaining = max(0, (expires_at - now).days)

    return {
        "is_downloaded": True,
        "is_expired": is_expired,
        "days_remaining": days_remaining,
        "expires_at": expires_at.isoformat()
    }
