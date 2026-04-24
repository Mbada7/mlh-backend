from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime

class CourseBase(BaseModel):
    course_code: str = Field(..., min_length=3, max_length=20, pattern=r'^[A-Z0-9]+$')
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    department: str = Field(..., min_length=2, max_length=100)
    semester: int = Field(..., ge=1, le=8)
    year: int = Field(..., ge=2020, le=2030)
    
    @validator('course_code')
    def validate_course_code(cls, v):
        if not v.isupper():
            raise ValueError('Course code must be uppercase')
        return v

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None

class CourseResponse(BaseModel):
    id: int
    course_code: str
    title: str
    description: Optional[str]
    department: str
    semester: int
    year: int
    lecturer_id: int
    lecturer_name: Optional[str] = None
    thumbnail: Optional[str] = None
    is_active: bool
    enrollment_count: int = 0
    video_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class EnrollmentBase(BaseModel):
    course_id: int

class EnrollmentCreate(EnrollmentBase):
    pass

class EnrollmentResponse(BaseModel):
    id: int
    user_id: int
    course_id: int
    course_title: str
    course_code: str
    progress: int
    enrolled_at: datetime
    last_accessed: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class CourseWithProgressResponse(CourseResponse):
    progress: Optional[int] = 0
    is_enrolled: bool = False
    last_watched_video_id: Optional[int] = None

