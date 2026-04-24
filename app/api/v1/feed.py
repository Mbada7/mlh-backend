# app/api/v1/feed.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.security import get_current_active_user, get_current_user_optional
from app.models.user import User
from app.schemas.video import VideoResponse
from app.services.recommendation_service import RecommendationService
from app.services.video_service import VideoService

router = APIRouter(prefix="/feed", tags=["Feed"])

@router.get("/personalized", response_model=List[VideoResponse])
async def get_personalized_feed(
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get personalized video feed for user"""
    recommendation_service = RecommendationService(db)
    video_service = VideoService(db)
    
    feed = await recommendation_service.get_personalized_feed(current_user.id, limit)
    
    # Convert to response format with uploader names
    result = []
    for video in feed:
        video_with_details = video_service.get_video_with_details(video.id, current_user.id)
        result.append(video_with_details)
    
    return result

@router.get("/trending", response_model=List[VideoResponse])
async def get_trending_feed(
    limit: int = Query(20, ge=1, le=50),
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db)
):
    """Get trending videos"""
    recommendation_service = RecommendationService(db)
    video_service = VideoService(db)
    
    trending = await recommendation_service.get_trending_videos(limit, days)
    
    result = []
    for video in trending:
        video_with_details = video_service.get_video_with_details(video.id)
        result.append(video_with_details)
    
    return result

@router.get("/similar/{video_id}", response_model=List[VideoResponse])
async def get_similar_videos(
    video_id: int,
    limit: int = Query(10, ge=1, le=20),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Get videos similar to specified video"""
    recommendation_service = RecommendationService(db)
    video_service = VideoService(db)
    
    similar = await recommendation_service.get_similar_videos(video_id, limit)
    
    user_id = current_user.id if current_user else None
    result = []
    for video in similar:
        video_with_details = video_service.get_video_with_details(video.id, user_id)
        result.append(video_with_details)
    
    return result

@router.get("/fresh", response_model=List[VideoResponse])
async def get_fresh_content(
    limit: int = Query(20, ge=1, le=50),
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db)
):
    """Get recently uploaded videos"""
    recommendation_service = RecommendationService(db)
    video_service = VideoService(db)
    
    fresh = await recommendation_service.get_fresh_videos(hours, limit)
    
    result = []
    for video in fresh:
        video_with_details = video_service.get_video_with_details(video.id)
        result.append(video_with_details)
    
    return result

@router.get("/for-you", response_model=List[VideoResponse])
async def get_for_you(
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Hybrid recommendations for the user"""
    recommendation_service = RecommendationService(db)
    video_service = VideoService(db)
    
    recommendations = await recommendation_service.get_user_recommendations(current_user.id, limit)
    
    result = []
    for video in recommendations:
        video_with_details = video_service.get_video_with_details(video.id, current_user.id)
        result.append(video_with_details)
    
    return result