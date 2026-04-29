from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.core.dependencies import require_admin, Pagination, get_pagination, get_cache_service
from app.models.user import User
from app.models.interaction import UserVideoInteraction
from app.models.video import Video  
from app.models.course import Course
from app.schemas.user import UserResponse, UserUpdate
from app.schemas.interaction import WatchHistoryResponse, UserEngagementSummary
from app.services.cache_service import CacheService
from app.services.ml_service import MLService
from app.core.config import settings
from datetime import datetime, timedelta
import os

router = APIRouter(prefix="/users", tags=["Users"])

# Add to your auth router
@router.get("/test-token")
async def test_token_creation(db: Session = Depends(get_db)):
    """Test token creation and validation"""
    from app.core.security import create_access_token, decode_token
    from datetime import datetime
    
    # Create a test user (use an existing user ID)
    test_user = db.query(User).first()
    if not test_user:
        return {"error": "No users found"}
    
    # Create token
    token_data = {"sub": str(test_user.id), "email": test_user.email, "role": test_user.role}
    access_token = create_access_token(data=token_data)
    
    # Try to decode it immediately
    try:
        decoded = decode_token(access_token)
        return {
            "success": True,
            "token_created_at": datetime.utcnow().isoformat(),
            "decoded_payload": decoded,
            "token": access_token
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "token": access_token
        }
        
@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_active_user)
):
    """Get current user's profile"""
    return current_user

@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    for field, value in user_update.dict(exclude_unset=True).items():
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    return current_user

# app/api/v1/users.py - Update get_watch_history

@router.get("/me/watch-history", response_model=List[WatchHistoryResponse])
async def get_watch_history(
    pagination: Pagination = Depends(get_pagination),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user's watch history with full thumbnail URLs"""
    
    # Get backend URL for constructing full URLs
    base_url = settings.BACKEND_URL.rstrip('/')
    
    # Query watch history
    history = db.query(
        UserVideoInteraction,
        Video.title,
        Video.thumbnail_url,
        Video.course_id,
        Video.duration
    ).join(
        Video, UserVideoInteraction.video_id == Video.id
    ).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.interaction_type == "view"
    ).order_by(
        UserVideoInteraction.created_at.desc()
    ).offset(pagination.skip).limit(pagination.limit).all()
    
    result = []
    for interaction, video_title, thumbnail_url, course_id, duration in history:
        # Get course title if exists
        course_title = None
        if course_id:
            course = db.query(Course).filter(Course.id == course_id).first()
            course_title = course.title if course else None
        
        # ✅ Build full thumbnail URL
        full_thumbnail_url = None
        if thumbnail_url:
            if thumbnail_url.startswith('http'):
                full_thumbnail_url = thumbnail_url
            else:
                full_thumbnail_url = f"{base_url}{thumbnail_url}"
        else:
            # If no thumbnail, try to get from stream endpoint
            full_thumbnail_url = f"{base_url}/api/v1/videos/thumbnail/{interaction.video_id}"
        
        result.append({
            "video_id": interaction.video_id,
            "video_title": video_title,
            "thumbnail_url": full_thumbnail_url,
            "watch_percentage": interaction.watch_percentage,
            "watch_duration": interaction.watch_duration,
            "watched_at": interaction.created_at,
            "course_id": course_id,
            "course_title": course_title,
            "completed": interaction.watch_percentage >= 0.9
        })
    
    return result


@router.get("/me/engagement", response_model=UserEngagementSummary)
async def get_user_engagement(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """Get user engagement summary"""
    
    # Try cache first
    cache_key = f"user:{current_user.id}:engagement"
    cached_result = await cache.get(cache_key)
    if cached_result:
        return cached_result
    
    # Calculate engagement metrics
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Get basic stats
    stats = db.query(
        UserVideoInteraction
    ).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.created_at >= thirty_days_ago
    ).all()
    
    videos_watched = len([s for s in stats if s.interaction_type == "view"])
    videos_liked = len([s for s in stats if s.interaction_type == "like"])
    comments_made = len([s for s in stats if s.interaction_type == "comment"])
    total_watch_time = sum(s.watch_duration for s in stats)
    
    # Get favorite categories (courses)
    course_counts = {}
    for stat in stats:
        if stat.video_id:
            video = db.query(Video).filter(Video.id == stat.video_id).first()
            if video and video.course_id:
                course_counts[video.course_id] = course_counts.get(video.course_id, 0) + 1
    
    favorite_categories = [str(cid) for cid, count in sorted(course_counts.items(), key=lambda x: x[1], reverse=True)[:3]]
    
    # Calculate engagement score using ML service
    ml_service = MLService(db)
    engagement_score = await ml_service.compute_engagement_score(current_user.id)
    
    result = UserEngagementSummary(
        user_id=current_user.id,
        username=current_user.username,
        videos_watched=videos_watched,
        videos_liked=videos_liked,
        comments_made=comments_made,
        total_watch_time=total_watch_time,
        favorite_categories=favorite_categories,
        peak_activity_hour=None,  # Would need additional tracking
        engagement_score=engagement_score
    )
    
    # Cache for 1 hour
    await cache.set(cache_key, result, 3600)
    
    return result

@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user by ID (only for admin or self)"""
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access forbidden")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user

@router.get("/", response_model=List[UserResponse])
async def get_all_users(
    pagination: Pagination = Depends(get_pagination),
    role: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get all users (admin only)"""
    query = db.query(User)
    
    if role:
        query = query.filter(User.role == role)
    
    users = query.offset(pagination.skip).limit(pagination.limit).all()
    return users

@router.post("/me/profile-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Upload profile picture"""
    import shutil
    import uuid
    
    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    # Save using absolute path — relative paths break on Windows + don't survive restarts
    base_upload_dir = settings.ABSOLUTE_STORAGE_PATH
    upload_dir = os.path.join(base_upload_dir, "profiles", str(current_user.id))
    os.makedirs(upload_dir, exist_ok=True)

    file_extension = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(upload_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Store absolute path in DB; return a URL the mobile app can display
    base_url = settings.BACKEND_URL.rstrip('/')
    profile_url = f"{base_url}/api/v1/users/me/avatar/{current_user.id}/{filename}"
    current_user.profile_picture = file_path
    db.commit()

    return {"profile_picture_url": profile_url}

@router.get("/me/bookmarks")
async def get_bookmarks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user's bookmarked videos"""
    base_url = settings.BACKEND_URL.rstrip('/')

    bookmarks = db.query(UserVideoInteraction).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.interaction_type == "bookmark"
    ).order_by(UserVideoInteraction.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for bookmark in bookmarks:
        video = db.query(Video).filter(Video.id == bookmark.video_id).first()
        if not video or not video.is_published:
            continue
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


@router.get("/me/recommendation-insights")
async def get_recommendation_insights(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user's recommendation insights and ML stats"""
    from datetime import datetime, timedelta
    from sqlalchemy import func as sqlfunc
    from app.models.recommendation import RecommendationFeedback

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Top interaction types (recommendation sources proxy)
    type_counts = db.query(
        UserVideoInteraction.interaction_type,
        sqlfunc.count(UserVideoInteraction.id).label("count")
    ).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.created_at >= thirty_days_ago
    ).group_by(UserVideoInteraction.interaction_type).all()

    source_map = {
        "view": "Browsing",
        "like": "Liked Content",
        "complete": "Completed Videos",
        "bookmark": "Bookmarked",
        "comment": "Commented"
    }

    top_sources = [
        {"source": source_map.get(t, t), "count": c}
        for t, c in sorted(type_counts, key=lambda x: x[1], reverse=True)
    ]

    # Feedback click rate
    feedback_count = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.user_id == current_user.id
    ).count()
    clicked_count = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.user_id == current_user.id,
        RecommendationFeedback.clicked == 1
    ).count()
    click_rate = (clicked_count / feedback_count * 100) if feedback_count > 0 else 0

    # Average engagement score on recommended items
    avg_watched = db.query(sqlfunc.avg(RecommendationFeedback.watched_duration)).filter(
        RecommendationFeedback.user_id == current_user.id
    ).scalar() or 0

    return {
        "top_recommendation_sources": top_sources,
        "recommendation_click_rate": round(click_rate, 1),
        "average_recommendation_engagement": round(float(avg_watched), 1)
    }


@router.get("/me/my-videos")
async def get_my_videos(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get current user's uploaded videos (including pending ones for students)"""
    base_url = settings.BACKEND_URL.rstrip('/')

    videos = db.query(Video).filter(
        Video.uploaded_by_user_id == current_user.id
    ).order_by(Video.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for video in videos:
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
            "uploader_name": current_user.full_name,
            "uploader_profile_picture": current_user.profile_picture,
            "tags": video.tags or [],
            "is_published": video.is_published,
            "is_featured": video.is_featured,
            "created_at": video.created_at,
            "approval_status": video.approval_status,
        })
    return result

@router.get("/me/avatar/{user_id}/{filename}")
async def serve_avatar(user_id: int, filename: str):
    """Serve a user profile picture by absolute path lookup"""
    file_path = os.path.join(settings.ABSOLUTE_STORAGE_PATH, "profiles", str(user_id), filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Profile picture not found")
    return FileResponse(path=file_path, media_type="image/jpeg")

@router.get("/me/liked-videos")
async def get_liked_videos(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from app.models.interaction import UserVideoInteraction
    from app.core.config import settings
    base_url = settings.BACKEND_URL.rstrip('/')
    interactions = db.query(UserVideoInteraction).filter(
        UserVideoInteraction.user_id == current_user.id,
        UserVideoInteraction.liked == True
    ).offset(skip).limit(limit).all()
    result = []
    for i in interactions:
        video = db.query(Video).filter(Video.id == i.video_id, Video.is_published == True).first()
        if not video:
            continue
        uploader = db.query(User).filter(User.id == video.uploaded_by_user_id).first()
        result.append({
            "id": video.id, "title": video.title, "description": video.description,
            "video_url": f"{base_url}/api/v1/videos/stream/{video.id}",
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video.id}" if video.thumbnail_url else None,
            "duration": video.duration, "view_count": video.view_count, "like_count": video.like_count,
            "comment_count": video.comment_count, "share_count": video.share_count,
            "course_id": video.course_id, "uploaded_by_user_id": video.uploaded_by_user_id,
            "uploader_name": uploader.full_name if uploader else "Unknown",
            "tags": video.tags or [], "is_published": video.is_published,
            "is_featured": video.is_featured, "created_at": video.created_at,
        })
    return result