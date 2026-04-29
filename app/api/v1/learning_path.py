from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.video import Video
from app.models.interaction import UserVideoInteraction
from app.models.quiz import Quiz, QuizAttempt
from app.core.config import settings

router = APIRouter(prefix="/learning-path", tags=["Learning Path"])


def fmt_video(v: Video, base_url: str, reason: str = "", difficulty: str = "intermediate") -> dict:
    return {
        "id": v.id, "title": v.title, "description": v.description,
        "video_url": f"{base_url}/api/v1/videos/stream/{v.id}",
        "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{v.id}" if v.thumbnail_url else None,
        "duration": v.duration, "view_count": v.view_count,
        "like_count": v.like_count, "comment_count": v.comment_count,
        "share_count": v.share_count, "course_id": v.course_id,
        "uploaded_by_user_id": v.uploaded_by_user_id,
        "uploader_name": "Lecturer", "tags": v.tags or [],
        "is_published": v.is_published, "is_featured": v.is_featured,
        "created_at": v.created_at,
        "path_reason": reason,
        "difficulty": difficulty,
    }


@router.get("/my-path")
async def get_my_learning_path(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Returns a personalised learning path based on:
    - Quiz scores (low score → revision videos; high score → advanced videos)
    - Watch history (what they haven't seen yet)
    - Course enrolments
    """
    uid = current_user.id
    base_url = settings.BACKEND_URL.rstrip('/')

    # Videos already watched
    watched_ids = {
        r.video_id for r in db.query(UserVideoInteraction.video_id).filter(
            UserVideoInteraction.user_id == uid,
            UserVideoInteraction.interaction_type == 'view'
        ).all()
    }

    # Recent quiz performance
    recent_attempts = db.query(QuizAttempt).filter(
        QuizAttempt.user_id == uid
    ).order_by(desc(QuizAttempt.completed_at)).limit(20).all()

    low_score_video_ids = set()   # videos where student scored < 50%
    high_score_video_ids = set()  # videos where student scored >= 70%

    for attempt in recent_attempts:
        quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
        if not quiz:
            continue
        if attempt.score < 50:
            low_score_video_ids.add(quiz.video_id)
        elif attempt.score >= 70:
            high_score_video_ids.add(quiz.video_id)

    path_sections = []

    # ── Section 1: Needs Revision ─────────────────────────────────────────────
    if low_score_video_ids:
        revision_videos = db.query(Video).filter(
            Video.id.in_(low_score_video_ids),
            Video.is_published == True
        ).limit(5).all()

        if revision_videos:
            path_sections.append({
                "section": "revision",
                "title": "📖 Needs Revision",
                "subtitle": "You scored below 50% on these topics. Review them to improve.",
                "priority": 1,
                "videos": [fmt_video(v, base_url, "Low quiz score — needs revision", "beginner")
                           for v in revision_videos]
            })

    # ── Section 2: Continue Learning ──────────────────────────────────────────
    # Videos from same courses as watched content, not yet seen
    if watched_ids:
        watched_videos = db.query(Video).filter(
            Video.id.in_(list(watched_ids)[:20])
        ).all()
        course_ids = {v.course_id for v in watched_videos if v.course_id}

        if course_ids:
            continue_videos = db.query(Video).filter(
                Video.course_id.in_(course_ids),
                Video.id.notin_(watched_ids),
                Video.is_published == True
            ).order_by(Video.created_at).limit(8).all()

            if continue_videos:
                path_sections.append({
                    "section": "continue",
                    "title": "▶ Continue Learning",
                    "subtitle": "Next videos in your enrolled courses.",
                    "priority": 2,
                    "videos": [fmt_video(v, base_url, "Next in your course", "intermediate")
                               for v in continue_videos]
                })

    # ── Section 3: Ready to Advance ───────────────────────────────────────────
    if high_score_video_ids:
        # Find videos tagged similarly but not yet watched
        high_videos = db.query(Video).filter(
            Video.id.in_(high_score_video_ids)
        ).all()
        good_tags = []
        for v in high_videos:
            good_tags.extend(v.tags or [])

        advanced_videos = db.query(Video).filter(
            Video.id.notin_(watched_ids),
            Video.is_published == True,
            Video.is_featured == True
        ).order_by(desc(Video.view_count)).limit(5).all()

        if not advanced_videos:
            advanced_videos = db.query(Video).filter(
                Video.id.notin_(watched_ids),
                Video.is_published == True
            ).order_by(desc(Video.like_count)).limit(5).all()

        if advanced_videos:
            path_sections.append({
                "section": "advanced",
                "title": "🚀 Ready to Advance",
                "subtitle": "You're excelling! Try these more challenging topics.",
                "priority": 3,
                "videos": [fmt_video(v, base_url, "High quiz score — ready to advance", "advanced")
                           for v in advanced_videos]
            })

    # ── Section 4: Discover New ───────────────────────────────────────────────
    fresh_videos = db.query(Video).filter(
        Video.id.notin_(watched_ids),
        Video.is_published == True
    ).order_by(desc(Video.created_at)).limit(6).all()

    if fresh_videos:
        path_sections.append({
            "section": "discover",
            "title": "✨ Discover New Content",
            "subtitle": "Fresh videos you haven't seen yet.",
            "priority": 4,
            "videos": [fmt_video(v, base_url, "New content for you", "intermediate")
                       for v in fresh_videos]
        })

    # ── Progress summary ──────────────────────────────────────────────────────
    total_published = db.query(func.count(Video.id)).filter(Video.is_published == True).scalar() or 1
    progress_pct = round((len(watched_ids) / total_published) * 100, 1)

    passed_quizzes = sum(1 for a in recent_attempts if a.passed)
    mastery_pct = round((passed_quizzes / len(recent_attempts)) * 100, 1) if recent_attempts else 0

    return {
        "summary": {
            "videos_watched": len(watched_ids),
            "total_videos": total_published,
            "platform_progress_pct": progress_pct,
            "quizzes_taken": len(recent_attempts),
            "quizzes_passed": passed_quizzes,
            "mastery_pct": mastery_pct,
            "needs_revision": len(low_score_video_ids),
            "ready_to_advance": len(high_score_video_ids),
        },
        "path": sorted(path_sections, key=lambda x: x["priority"])
    }


@router.get("/topic-mastery")
async def get_topic_mastery(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Returns topic-level mastery scores based on quiz performance"""
    attempts = db.query(QuizAttempt).filter(
        QuizAttempt.user_id == current_user.id
    ).all()

    mastery = {}
    for attempt in attempts:
        quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
        if not quiz:
            continue
        topic = quiz.title
        if topic not in mastery:
            mastery[topic] = {"scores": [], "video_id": quiz.video_id}
        mastery[topic]["scores"].append(attempt.score)

    result = []
    for topic, data in mastery.items():
        scores = data["scores"]
        avg = round(sum(scores) / len(scores), 1)
        result.append({
            "topic": topic,
            "video_id": data["video_id"],
            "avg_score": avg,
            "attempts": len(scores),
            "best_score": max(scores),
            "mastery_level": "mastered" if avg >= 80 else "learning" if avg >= 50 else "struggling",
            "mastery_color": "#16a34a" if avg >= 80 else "#d97706" if avg >= 50 else "#dc2626",
        })

    return sorted(result, key=lambda x: x["avg_score"], reverse=True)
