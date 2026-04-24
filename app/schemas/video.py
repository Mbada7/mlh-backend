# app/schemas/video.py - FIXED Version
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class VideoBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    course_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)

class VideoCreate(VideoBase):
    pass

class VideoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    is_published: Optional[bool] = None

class VideoResponse(VideoBase):
    id: int
    video_url: str
    thumbnail_url: Optional[str]
    duration: Optional[int]
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    uploaded_by_user_id: int
    uploader_name: str  # ✅ This field is REQUIRED
    uploader_profile_picture: Optional[str] = None  # ✅ Add this too
    is_published: bool
    is_featured: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class VideoUploadResponse(BaseModel):
    video_id: int
    upload_url: str
    fields: Optional[dict] = None

class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    parent_comment_id: Optional[int] = None

class CommentResponse(BaseModel):
    id: int
    content: str
    user_id: int
    username: str
    user_profile_picture: Optional[str]
    like_count: int
    created_at: datetime
    replies: List['CommentResponse'] = []
    
    class Config:
        from_attributes = True

CommentResponse.model_rebuild()