# app/api/v1/courses.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.security import get_current_active_user, get_current_lecturer_user
from app.models.user import User
from app.models.course import Course, Enrollment
from app.schemas.course import CourseCreate, CourseResponse, CourseWithProgressResponse
from app.schemas.video import VideoResponse
from app.models.video import Video
from app.core.config import settings

router = APIRouter(prefix="/courses", tags=["Courses"])


# ─── STATIC ROUTES MUST COME BEFORE /{course_id} WILDCARD ────────────────────

@router.get("/my-courses", response_model=List[CourseResponse])
async def get_my_courses(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get courses the current user is enrolled in"""
    base_url = settings.BACKEND_URL.rstrip('/')

    enrollments = db.query(Enrollment).filter(
        Enrollment.user_id == current_user.id
    ).all()

    course_ids = [e.course_id for e in enrollments]
    if not course_ids:
        return []

    courses = db.query(Course).filter(Course.id.in_(course_ids)).all()

    result = []
    for course in courses:
        lecturer = db.query(User).filter(User.id == course.lecturer_id).first()
        enrollment_count = db.query(Enrollment).filter(Enrollment.course_id == course.id).count()
        video_count = db.query(Video).filter(Video.course_id == course.id).count()

        full_thumbnail_url = None
        if course.thumbnail:
            if course.thumbnail.startswith('http'):
                full_thumbnail_url = course.thumbnail
            else:
                full_thumbnail_url = f"{base_url}{course.thumbnail}"

        result.append({
            "id": course.id,
            "course_code": course.course_code,
            "title": course.title,
            "description": course.description,
            "department": course.department,
            "semester": course.semester,
            "year": course.year,
            "lecturer_id": course.lecturer_id,
            "lecturer_name": lecturer.full_name if lecturer else None,
            "thumbnail": full_thumbnail_url,
            "is_active": course.is_active,
            "enrollment_count": enrollment_count,
            "video_count": video_count,
            "created_at": course.created_at,
            "updated_at": course.updated_at
        })

    return result


@router.get("/lecturer/courses", response_model=List[CourseResponse])
async def get_lecturer_courses(
    current_user: User = Depends(get_current_lecturer_user),
    db: Session = Depends(get_db),
):
    """Get courses taught by the current lecturer"""
    courses = db.query(Course).filter(Course.lecturer_id == current_user.id).all()

    result = []
    for course in courses:
        enrollment_count = db.query(Enrollment).filter(Enrollment.course_id == course.id).count()
        video_count = db.query(Video).filter(Video.course_id == course.id).count()

        result.append({
            "id": course.id,
            "course_code": course.course_code,
            "title": course.title,
            "description": course.description,
            "department": course.department,
            "semester": course.semester,
            "year": course.year,
            "lecturer_id": course.lecturer_id,
            "lecturer_name": current_user.full_name,
            "thumbnail": course.thumbnail,
            "is_active": course.is_active,
            "enrollment_count": enrollment_count,
            "video_count": video_count,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
        })

    return result


# ─── COLLECTION ROUTES ────────────────────────────────────────────────────────

@router.post("/", response_model=CourseResponse)
async def create_course(
    course_data: CourseCreate,
    current_user: User = Depends(get_current_lecturer_user),
    db: Session = Depends(get_db),
):
    """Create a new course (lecturers only)"""
    existing = db.query(Course).filter(Course.course_code == course_data.course_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Course code already exists")

    course = Course(
        course_code=course_data.course_code,
        title=course_data.title,
        description=course_data.description,
        department=course_data.department,
        semester=course_data.semester,
        year=course_data.year,
        lecturer_id=current_user.id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    return {
        **course.__dict__,
        "lecturer_name": current_user.full_name,
        "enrollment_count": 0,
        "video_count": 0,
    }


@router.get("/", response_model=List[CourseResponse])
async def get_courses(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    department: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all courses with optional filters"""
    query = db.query(Course).filter(Course.is_active == True)

    if department:
        query = query.filter(Course.department == department)

    courses = query.offset(skip).limit(limit).all()

    result = []
    for course in courses:
        lecturer = db.query(User).filter(User.id == course.lecturer_id).first()
        enrollment_count = db.query(Enrollment).filter(Enrollment.course_id == course.id).count()
        video_count = db.query(Video).filter(Video.course_id == course.id).count()

        result.append({
            "id": course.id,
            "course_code": course.course_code,
            "title": course.title,
            "description": course.description,
            "department": course.department,
            "semester": course.semester,
            "year": course.year,
            "lecturer_id": course.lecturer_id,
            "lecturer_name": lecturer.full_name if lecturer else None,
            "thumbnail": course.thumbnail,
            "is_active": course.is_active,
            "enrollment_count": enrollment_count,
            "video_count": video_count,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
        })

    return result


# ─── PARAMETERISED ROUTES (must come AFTER all static /path routes) ───────────

@router.get("/{course_id}", response_model=CourseWithProgressResponse)
async def get_course_details(
    course_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get detailed course information"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == current_user.id, Enrollment.course_id == course_id)
        .first()
    )

    lecturer = db.query(User).filter(User.id == course.lecturer_id).first()
    enrollment_count = db.query(Enrollment).filter(Enrollment.course_id == course_id).count()
    video_count = db.query(Video).filter(Video.course_id == course_id).count()

    last_watched = (
        db.query(Video)
        .join(Enrollment, Video.course_id == Enrollment.course_id)
        .filter(Enrollment.user_id == current_user.id, Video.course_id == course_id)
        .order_by(Video.created_at.desc())
        .first()
    )

    return {
        "id": course.id,
        "course_code": course.course_code,
        "title": course.title,
        "description": course.description,
        "department": course.department,
        "semester": course.semester,
        "year": course.year,
        "lecturer_id": course.lecturer_id,
        "lecturer_name": lecturer.full_name if lecturer else None,
        "thumbnail": course.thumbnail,
        "is_active": course.is_active,
        "enrollment_count": enrollment_count,
        "video_count": video_count,
        "created_at": course.created_at,
        "updated_at": course.updated_at,
        "progress": enrollment.progress if enrollment else 0,
        "is_enrolled": enrollment is not None,
        "last_watched_video_id": last_watched.id if last_watched else None,
    }


@router.post("/{course_id}/enroll")
async def enroll_in_course(
    course_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Enroll in a course"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == current_user.id, Enrollment.course_id == course_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already enrolled in this course")

    enrollment = Enrollment(user_id=current_user.id, course_id=course_id, progress=0)
    db.add(enrollment)
    db.commit()

    return {"message": f"Successfully enrolled in {course.title}", "course_id": course_id}


@router.delete("/{course_id}/unenroll")
async def unenroll_from_course(
    course_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Unenroll from a course"""
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == current_user.id, Enrollment.course_id == course_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Not enrolled in this course")

    db.delete(enrollment)
    db.commit()

    return {"message": "Successfully unenrolled from course"}


@router.get("/{course_id}/videos", response_model=List[VideoResponse])
async def get_course_videos(
    course_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all videos for a course"""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    videos = (
        db.query(Video)
        .filter(Video.course_id == course_id, Video.is_published == True)
        .order_by(Video.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    base_url = settings.BACKEND_URL.rstrip("/")

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
            "created_at": video.created_at,
        })

    return result
