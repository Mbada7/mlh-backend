from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

class InteractionType(str, Enum):
    VIEW = "view"
    LIKE = "like"
    COMMENT = "comment"
    SHARE = "share"
    BOOKMARK = "bookmark"
    COMPLETE = "complete"
    SKIP = "skip"
    SEARCH = "search"

class InteractionBase(BaseModel):
    video_id: int
    interaction_type: InteractionType
    watch_percentage: float = Field(0.0, ge=0.0, le=1.0)
    watch_duration: int = Field(0, ge=0)  # seconds

class InteractionCreate(InteractionBase):
    pass

class InteractionResponse(InteractionBase):
    id: int
    user_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class WatchHistoryResponse(BaseModel):
    video_id: int
    video_title: str
    thumbnail_url: Optional[str]
    watch_percentage: float
    watch_duration: int
    watched_at: datetime
    course_id: Optional[int]
    course_title: Optional[str]
    completed: bool = False  # ✅ Add this field
    
    class Config:
        from_attributes = True

class EngagementStats(BaseModel):
    total_views: int
    total_likes: int
    total_comments: int
    total_shares: int
    total_watch_time: int  # in seconds
    average_watch_percentage: float
    engagement_rate: float  # (likes+comments+shares)/views
    
class UserEngagementSummary(BaseModel):
    user_id: int
    username: str
    videos_watched: int
    videos_liked: int
    comments_made: int
    total_watch_time: int
    favorite_categories: List[str]
    peak_activity_hour: Optional[int]
    engagement_score: float  # 0-100 score
    
class BatchInteractionCreate(BaseModel):
    interactions: List[InteractionCreate]
    
    @validator('interactions')
    def validate_batch_size(cls, v):
        if len(v) > 100:
            raise ValueError('Maximum 100 interactions per batch')
        return v