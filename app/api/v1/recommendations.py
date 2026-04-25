# app/api/v1/recommendations.py
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.core.dependencies import get_cache_service
from app.models.user import User
from app.models.video import Video
from app.models.interaction import UserVideoInteraction
from app.schemas.video import VideoResponse
from app.services.recommendation_service import RecommendationService
from app.services.ml_service import MLService
from app.services.cache_service import CacheService
from app.services.video_service import VideoService
from app.models.recommendation import RecommendationFeedback

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

@router.get("/personalized", response_model=List[VideoResponse])
async def get_personalized_recommendations(
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """Get personalized video recommendations for user"""
    
    cache_key = f"rec:{current_user.id}:personalized:{limit}"
    
    # Check cache
    if not refresh:
        cached_recommendations = await cache.get(cache_key)
        if cached_recommendations:
            return cached_recommendations
    
    # Generate recommendations
    rec_service = RecommendationService(db)
    video_service = VideoService(db)
    
    recommendations = await rec_service.get_personalized_feed(current_user.id, limit)
    
    # Convert to serializable format
    result = []
    for video in recommendations:
        video_dict = video_service.get_video_with_details(video.id, current_user.id)
        result.append(video_dict)
    
    # Cache for 5 minutes
    await cache.set(cache_key, result, 300)
    
    return result

@router.get("/trending", response_model=List[VideoResponse])
async def get_trending_recommendations(
    limit: int = Query(20, ge=1, le=50),
    days: int = Query(7, ge=1, le=30),
    current_user: Optional[User] = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """Get trending videos based on recent engagement"""
    cache_key = f"trending:limit:{limit}:days:{days}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    rec_service = RecommendationService(db)
    video_service = VideoService(db)

    trending = await rec_service.get_trending_videos(limit, days)

    result = []
    for video in trending:
        user_id = current_user.id if current_user else None
        video_dict = video_service.get_video_with_details(video.id, user_id)
        result.append(video_dict)

    await cache.set(cache_key, result, 600)
    return result

@router.get("/similar/{video_id}", response_model=List[VideoResponse])
async def get_similar_videos(
    video_id: int,
    limit: int = Query(10, ge=1, le=20),
    current_user: Optional[User] = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """Get videos similar to specified video"""
    
    cache_key = f"rec:similar:{video_id}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    rec_service = RecommendationService(db)
    video_service = VideoService(db)
    
    similar = await rec_service.get_similar_videos(video_id, limit)
    
    # Convert to serializable format
    user_id = current_user.id if current_user else None
    result = []
    for video in similar:
        video_dict = video_service.get_video_with_details(video.id, user_id)
        result.append(video_dict)
    
    await cache.set(cache_key, result, 3600)  # Cache for 1 hour
    
    return result

@router.get("/for-you", response_model=List[VideoResponse])
async def get_for_you_page(
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """Hybrid recommendations combining multiple strategies"""
    
    cache_key = f"rec:{current_user.id}:foryou:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    rec_service = RecommendationService(db)
    video_service = VideoService(db)
    
    # Get recommendations from different sources
    personalized = await rec_service.get_personalized_feed(current_user.id, limit // 2)
    trending = await rec_service.get_trending_videos(limit // 4)
    
    # Get fresh content (videos from last 24 hours)
    fresh = await rec_service.get_fresh_videos(24, limit // 4)
    
    # Combine and deduplicate
    seen_ids = set()
    combined = []
    
    for video in personalized + trending + fresh:
        if video.id not in seen_ids:
            video_dict = video_service.get_video_with_details(video.id, current_user.id)
            combined.append(video_dict)
            seen_ids.add(video.id)
            if len(combined) >= limit:
                break
    
    await cache.set(cache_key, combined, 300)  # Cache for 5 minutes
    
    return combined

@router.get("/course-based", response_model=List[VideoResponse])
async def get_course_based_recommendations(
    course_id: int,
    limit: int = Query(10, ge=1, le=20),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get video recommendations for a specific course based on user progress"""
    
    video_service = VideoService(db)
    
    # Get videos from the course
    course_videos = db.query(Video).filter(
        Video.course_id == course_id,
        Video.is_published,
        Video.id.notin_(
            db.query(UserVideoInteraction.video_id).filter(
                UserVideoInteraction.user_id == current_user.id,
                UserVideoInteraction.interaction_type == 'complete'
            )
        )
    ).order_by(Video.created_at).limit(limit).all()
    
    # Convert to serializable format
    result = []
    for video in course_videos:
        video_dict = video_service.get_video_with_details(video.id, current_user.id)
        result.append(video_dict)
    
    return result

@router.get("/explore")
async def get_explore_page(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    cache: CacheService = Depends(get_cache_service)
):
    """
    Get curated explore page with multiple recommendation categories.
    FIXED: Returns proper JSON-serializable data
    """
    
    cache_key = f"rec:{current_user.id}:explore"
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    rec_service = RecommendationService(db)
    video_service = VideoService(db)
    
    # Get different recommendation categories
    trending = await rec_service.get_trending_videos(10)
    personalized = await rec_service.get_personalized_feed(current_user.id, 10)
    
    # Get user's department
    user = db.query(User).filter(User.id == current_user.id).first()
    department_videos = []
    if user and user.department:
        department_videos = await rec_service.get_popular_in_department(user.department, 10)
    
    # Get "because you watched" — seed from the first personalized video.
    # BUG WAS: get_similar_videos(current_user.id) passed a USER id as a video id.
    because_you_watched = []
    if personalized:
        seed_video_id = personalized[0].id
        because_you_watched = await rec_service.get_similar_videos(seed_video_id, 10)

    # Get editor picks (featured approved videos only)
    editor_picks = db.query(Video).filter(
        Video.is_featured,
        Video.is_published == True,
        Video.approval_status == "approved"
    ).order_by(Video.created_at.desc()).limit(10).all()
    
    # Convert all to serializable format
    result = {
        "trending": [],
        "recommended_for_you": [],
        "popular_in_department": [],
        "because_you_watched": [],
        "editor_picks": []
    }
    
    # Serialize each category
    for video in trending:
        result["trending"].append(video_service.get_video_with_details(video.id, current_user.id))
    
    for video in personalized:
        result["recommended_for_you"].append(video_service.get_video_with_details(video.id, current_user.id))
    
    for video in department_videos:
        result["popular_in_department"].append(video_service.get_video_with_details(video.id, current_user.id))
    
    for video in because_you_watched[:10]:
        if isinstance(video, Video):
            result["because_you_watched"].append(video_service.get_video_with_details(video.id, current_user.id))
    
    for video in editor_picks:
        result["editor_picks"].append(video_service.get_video_with_details(video.id, current_user.id))
    
    await cache.set(cache_key, result, 300)  # Cache for 5 minutes
    
    return result

@router.get("/popular/{department}")
async def get_popular_in_department(
    department: str,
    limit: int = Query(10, ge=1, le=20),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get popular videos in a specific department"""
    
    rec_service = RecommendationService(db)
    video_service = VideoService(db)
    
    popular = await rec_service.get_popular_in_department(department, limit)
    
    result = []
    for video in popular:
        result.append(video_service.get_video_with_details(video.id, current_user.id))
    
    return result

@router.post("/feedback")
async def submit_recommendation_feedback(
    feedback_data: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Submit feedback on recommendations for model improvement"""
    
    feedback = RecommendationFeedback(
        user_id=current_user.id,
        video_id=feedback_data.get('video_id'),
        recommendation_id=feedback_data.get('recommendation_id'),
        position=feedback_data.get('position', 0),
        clicked=feedback_data.get('clicked', 0),
        watched_duration=feedback_data.get('watched_duration', 0),
        liked=feedback_data.get('liked', 0),
        feedback_score=feedback_data.get('feedback_score', 0.0)
    )
    
    db.add(feedback)
    db.commit()
    
    # Invalidate user's recommendation cache
    cache = CacheService()
    await cache.clear_user_cache(current_user.id)
    
    return {"status": "feedback_received"}

@router.post("/retrain-model")
async def retrain_recommendation_model(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Trigger model retraining (admin only)"""
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Run retraining in background
    ml_service = MLService(db)
    background_tasks.add_task(ml_service.update_recommendation_model)
    
    return {"status": "model_retraining_started"}

@router.get("/user-embeddings/{user_id}")
async def get_user_embeddings(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get user embedding vector (for debugging)"""
    
    if current_user.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access forbidden")
    
    ml_service = MLService(db)
    embedding = await ml_service.generate_user_embeddings(user_id)
    
    return {
        "user_id": user_id,
        "embedding_shape": embedding.shape,
        "embedding_sample": embedding[:10].tolist()  # Return first 10 values
    }