from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User, UserRole
from app.models.video import Video, Comment
from app.models.interaction import UserVideoInteraction
from app.models.quiz import QuizAttempt, Quiz
from app.models.analytics import LearningStreak, VideoDropOff, DailyLearningLog

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def require_lecturer_or_admin(current_user: User = Depends(get_current_active_user)):
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role not in ["lecturer", "admin"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Lecturer or admin access required")
    return current_user


def require_admin(current_user: User = Depends(get_current_active_user)):
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ─── Streak Tracking ──────────────────────────────────────────────────────────
def update_streak(user_id: int, db: Session):
    """Call this whenever a user watches a video or takes a quiz"""
    today = date.today()
    streak = db.query(LearningStreak).filter(LearningStreak.user_id == user_id).first()

    if not streak:
        streak = LearningStreak(user_id=user_id, current_streak=1, longest_streak=1,
                                last_activity_date=today, total_study_days=1)
        db.add(streak)
        db.commit()
        return streak

    last = streak.last_activity_date
    if last == today:
        return streak  # already counted today

    yesterday = today - timedelta(days=1)
    if last == yesterday:
        streak.current_streak += 1
    else:
        streak.current_streak = 1  # streak broken

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak

    streak.last_activity_date = today
    streak.total_study_days += 1
    db.commit()
    return streak


# ─── STUDENT ANALYTICS ───────────────────────────────────────────────────────
@router.get("/student/dashboard")
async def student_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Full student learning analytics dashboard"""
    uid = current_user.id
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # ── Watch stats ───────────────────────────────────────────────────────────
    total_watch = db.query(
        func.count(UserVideoInteraction.id),
        func.coalesce(func.sum(UserVideoInteraction.watch_duration), 0)
    ).filter(
        UserVideoInteraction.user_id == uid,
        UserVideoInteraction.interaction_type == 'view'
    ).first()

    videos_watched = total_watch[0] or 0
    total_seconds = int(total_watch[1] or 0)

    # This week vs last week
    this_week = db.query(func.count(UserVideoInteraction.id)).filter(
        UserVideoInteraction.user_id == uid,
        UserVideoInteraction.interaction_type == 'view',
        func.date(UserVideoInteraction.created_at) >= week_ago
    ).scalar() or 0

    last_week_start = week_ago - timedelta(days=7)
    last_week = db.query(func.count(UserVideoInteraction.id)).filter(
        UserVideoInteraction.user_id == uid,
        UserVideoInteraction.interaction_type == 'view',
        func.date(UserVideoInteraction.created_at) >= last_week_start,
        func.date(UserVideoInteraction.created_at) < week_ago
    ).scalar() or 0

    # ── Quiz stats ────────────────────────────────────────────────────────────
    quiz_stats = db.query(
        func.count(QuizAttempt.id),
        func.coalesce(func.avg(QuizAttempt.score), 0),
        func.sum(func.cast(QuizAttempt.passed, Integer) if hasattr(QuizAttempt.passed, 'cast') else QuizAttempt.passed)
    ).filter(QuizAttempt.user_id == uid).first()

    quizzes_taken = quiz_stats[0] or 0
    avg_quiz_score = round(float(quiz_stats[1] or 0), 1)

    # Quiz score trend (last 10 attempts)
    recent_attempts = db.query(QuizAttempt).filter(
        QuizAttempt.user_id == uid
    ).order_by(desc(QuizAttempt.completed_at)).limit(10).all()

    score_trend = [
        {"attempt": i + 1, "score": a.score, "passed": a.passed,
         "date": a.completed_at.strftime("%b %d") if a.completed_at else ""}
        for i, a in enumerate(reversed(recent_attempts))
    ]

    # ── Streak ────────────────────────────────────────────────────────────────
    streak = db.query(LearningStreak).filter(LearningStreak.user_id == uid).first()
    current_streak = streak.current_streak if streak else 0
    longest_streak = streak.longest_streak if streak else 0
    total_study_days = streak.total_study_days if streak else 0

    # ── Daily activity (last 7 days) ──────────────────────────────────────────
    daily_activity = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = db.query(func.count(UserVideoInteraction.id)).filter(
            UserVideoInteraction.user_id == uid,
            UserVideoInteraction.interaction_type == 'view',
            func.date(UserVideoInteraction.created_at) == day
        ).scalar() or 0
        daily_activity.append({
            "date": day.strftime("%a"),
            "full_date": day.isoformat(),
            "videos_watched": count
        })

    # ── Completion rates ──────────────────────────────────────────────────────
    completions = db.query(func.count(UserVideoInteraction.id)).filter(
        UserVideoInteraction.user_id == uid,
        UserVideoInteraction.interaction_type == 'view',
        UserVideoInteraction.watch_percentage >= 90
    ).scalar() or 0

    completion_rate = round((completions / videos_watched * 100), 1) if videos_watched > 0 else 0

    # ── Strongest / weakest topics via quiz ───────────────────────────────────
    topic_performance = []
    quiz_with_scores = db.query(
        Quiz.title,
        func.avg(QuizAttempt.score).label('avg_score'),
        func.count(QuizAttempt.id).label('attempts')
    ).join(QuizAttempt, QuizAttempt.quiz_id == Quiz.id).filter(
        QuizAttempt.user_id == uid
    ).group_by(Quiz.id, Quiz.title).order_by(desc('avg_score')).limit(10).all()

    for q in quiz_with_scores:
        topic_performance.append({
            "topic": q.title,
            "avg_score": round(float(q.avg_score), 1),
            "attempts": q.attempts,
            "level": "strong" if q.avg_score >= 70 else "weak"
        })

    # ── Weekly summary ────────────────────────────────────────────────────────
    week_change = this_week - last_week
    week_change_pct = round((week_change / last_week * 100), 1) if last_week > 0 else 0

    return {
        "overview": {
            "videos_watched": videos_watched,
            "total_hours": round(total_seconds / 3600, 1),
            "total_minutes": round(total_seconds / 60),
            "quizzes_taken": quizzes_taken,
            "avg_quiz_score": avg_quiz_score,
            "completion_rate": completion_rate,
            "completions": completions,
        },
        "streak": {
            "current": current_streak,
            "longest": longest_streak,
            "total_study_days": total_study_days,
            "is_active_today": streak.last_activity_date == today if streak else False,
        },
        "weekly_comparison": {
            "this_week": this_week,
            "last_week": last_week,
            "change": week_change,
            "change_pct": week_change_pct,
            "improving": week_change >= 0,
        },
        "daily_activity": daily_activity,
        "score_trend": score_trend,
        "topic_performance": topic_performance,
    }


# ─── LECTURER ANALYTICS ──────────────────────────────────────────────────────
@router.get("/lecturer/dashboard")
async def lecturer_dashboard(
    current_user: User = Depends(require_lecturer_or_admin),
    db: Session = Depends(get_db)
):
    """Lecturer analytics — engagement on their videos"""
    uid = current_user.id

    # Their videos
    my_videos = db.query(Video).filter(
        Video.uploaded_by_user_id == uid,
        Video.is_published == True
    ).all()

    total_views = sum(v.view_count for v in my_videos)
    total_likes = sum(v.like_count for v in my_videos)
    total_comments = sum(v.comment_count for v in my_videos)

    # Per-video breakdown
    video_stats = []
    for v in sorted(my_videos, key=lambda x: x.view_count, reverse=True)[:20]:
        # Avg watch percentage for this video
        avg_watch = db.query(func.avg(UserVideoInteraction.watch_percentage)).filter(
            UserVideoInteraction.video_id == v.id,
            UserVideoInteraction.interaction_type == 'view'
        ).scalar() or 0

        # Drop-off point
        drop_offs = db.query(func.avg(VideoDropOff.drop_off_percentage)).filter(
            VideoDropOff.video_id == v.id
        ).scalar() or 0

        # Quiz performance on this video
        quiz = db.query(Quiz).filter(Quiz.video_id == v.id).first()
        quiz_avg = None
        if quiz:
            quiz_avg = db.query(func.avg(QuizAttempt.score)).filter(
                QuizAttempt.quiz_id == quiz.id
            ).scalar()
            quiz_avg = round(float(quiz_avg), 1) if quiz_avg else None

        video_stats.append({
            "id": v.id,
            "title": v.title,
            "view_count": v.view_count,
            "like_count": v.like_count,
            "comment_count": v.comment_count,
            "avg_watch_pct": round(float(avg_watch), 1),
            "avg_drop_off": round(float(drop_offs), 1),
            "has_quiz": quiz is not None,
            "avg_quiz_score": quiz_avg,
        })

    # Unique students who watched their content
    unique_students = db.query(func.count(func.distinct(UserVideoInteraction.user_id))).filter(
        UserVideoInteraction.video_id.in_([v.id for v in my_videos]),
        UserVideoInteraction.interaction_type == 'view'
    ).scalar() or 0

    # Views per day last 7 days
    today = date.today()
    daily_views = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = db.query(func.count(UserVideoInteraction.id)).filter(
            UserVideoInteraction.video_id.in_([v.id for v in my_videos]),
            UserVideoInteraction.interaction_type == 'view',
            func.date(UserVideoInteraction.created_at) == day
        ).scalar() or 0
        daily_views.append({"date": day.strftime("%a"), "views": count})

    return {
        "overview": {
            "total_videos": len(my_videos),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "unique_students": unique_students,
            "avg_views_per_video": round(total_views / len(my_videos), 1) if my_videos else 0,
        },
        "video_stats": video_stats,
        "daily_views": daily_views,
    }


# ─── ADMIN ANALYTICS ─────────────────────────────────────────────────────────
@router.get("/admin/dashboard")
async def admin_analytics(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Platform-wide analytics for admin"""
    today = date.today()
    week_ago = today - timedelta(days=7)

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_videos = db.query(func.count(Video.id)).filter(Video.is_published == True).scalar() or 0
    total_views = db.query(func.sum(Video.view_count)).scalar() or 0
    total_likes = db.query(func.sum(Video.like_count)).scalar() or 0
    total_comments = db.query(func.sum(Video.comment_count)).scalar() or 0
    total_quizzes = db.query(func.count(QuizAttempt.id)).scalar() or 0

    # New users this week
    new_users_week = db.query(func.count(User.id)).filter(
        func.date(User.created_at) >= week_ago
    ).scalar() or 0

    # Active users this week
    active_week = db.query(func.count(func.distinct(UserVideoInteraction.user_id))).filter(
        func.date(UserVideoInteraction.created_at) >= week_ago
    ).scalar() or 0

    # Daily activity last 14 days
    daily_activity = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        views = db.query(func.count(UserVideoInteraction.id)).filter(
            UserVideoInteraction.interaction_type == 'view',
            func.date(UserVideoInteraction.created_at) == day
        ).scalar() or 0
        daily_activity.append({"date": day.strftime("%b %d"), "views": views})

    # Top 10 most watched videos
    top_videos = db.query(Video).filter(Video.is_published == True).order_by(
        desc(Video.view_count)
    ).limit(10).all()

    top_videos_data = [{"id": v.id, "title": v.title, "view_count": v.view_count,
                         "like_count": v.like_count} for v in top_videos]

    # Users by role
    from app.models.user import UserRole as UR
    students = db.query(func.count(User.id)).filter(User.role == UR.STUDENT).scalar() or 0
    lecturers = db.query(func.count(User.id)).filter(User.role == UR.LECTURER).scalar() or 0
    admins = db.query(func.count(User.id)).filter(User.role == UR.ADMIN).scalar() or 0

    return {
        "overview": {
            "total_users": total_users, "total_videos": total_videos,
            "total_views": total_views, "total_likes": total_likes,
            "total_comments": total_comments, "total_quiz_attempts": total_quizzes,
            "new_users_this_week": new_users_week, "active_users_this_week": active_week,
        },
        "users_by_role": {"students": students, "lecturers": lecturers, "admins": admins},
        "daily_activity": daily_activity,
        "top_videos": top_videos_data,
    }


# ─── Streak update endpoint ───────────────────────────────────────────────────
@router.post("/streak/update")
async def update_user_streak(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Call this when a user watches a video or takes a quiz"""
    streak = update_streak(current_user.id, db)
    return {
        "current_streak": streak.current_streak,
        "longest_streak": streak.longest_streak,
        "total_study_days": streak.total_study_days,
    }


# needed for sql aggregate on boolean
from sqlalchemy import Integer as SqlInt
