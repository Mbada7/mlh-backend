from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.video import Video
from app.models.interaction import UserVideoInteraction
from app.models.quiz import QuizAttempt
from app.models.peer_learning import DiscussionThread, DiscussionReply
from app.models.analytics import LearningStreak

router = APIRouter(prefix="/peer", tags=["Peer Learning"])


class ThreadCreate(BaseModel):
    video_id: int
    title: str
    content: str


class ReplyCreate(BaseModel):
    content: str


# ─── Discussion Threads ───────────────────────────────────────────────────────
@router.post("/threads", response_model=dict)
async def create_thread(
    data: ThreadCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Start a discussion thread on a video"""
    if len(data.title.strip()) < 5:
        raise HTTPException(status_code=400, detail="Title must be at least 5 characters")
    if len(data.content.strip()) < 10:
        raise HTTPException(status_code=400, detail="Content must be at least 10 characters")

    thread = DiscussionThread(
        video_id=data.video_id,
        user_id=current_user.id,
        title=data.title.strip(),
        content=data.content.strip()
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return {"id": thread.id, "message": "Thread created"}


@router.get("/threads/video/{video_id}", response_model=List[dict])
async def get_threads(
    video_id: int,
    skip: int = 0, limit: int = 30,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all discussion threads for a video"""
    threads = db.query(DiscussionThread).filter(
        DiscussionThread.video_id == video_id
    ).order_by(
        DiscussionThread.is_resolved,         # unresolved first
        desc(DiscussionThread.created_at)
    ).offset(skip).limit(limit).all()

    result = []
    for t in threads:
        author = db.query(User).filter(User.id == t.user_id).first()
        result.append({
            "id": t.id, "title": t.title, "content": t.content,
            "is_resolved": t.is_resolved, "reply_count": t.reply_count,
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "author": {
                "id": t.user_id,
                "name": author.full_name if author else "Unknown",
                "role": author.role.value if author and hasattr(author.role, 'value') else str(author.role) if author else "",
                "initials": (author.full_name[:1].upper() if author else "?"),
            },
            "is_mine": t.user_id == current_user.id,
        })
    return result


@router.get("/threads/{thread_id}", response_model=dict)
async def get_thread_detail(
    thread_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get a thread with all replies"""
    thread = db.query(DiscussionThread).filter(DiscussionThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    author = db.query(User).filter(User.id == thread.user_id).first()
    replies_raw = db.query(DiscussionReply).filter(
        DiscussionReply.thread_id == thread_id
    ).order_by(DiscussionReply.is_verified.desc(), DiscussionReply.created_at).all()

    replies = []
    for r in replies_raw:
        u = db.query(User).filter(User.id == r.user_id).first()
        replies.append({
            "id": r.id, "content": r.content,
            "is_verified": r.is_verified, "like_count": r.like_count,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "author": {
                "id": r.user_id,
                "name": u.full_name if u else "Unknown",
                "role": u.role.value if u and hasattr(u.role, 'value') else str(u.role) if u else "",
                "initials": u.full_name[:1].upper() if u else "?",
            },
            "is_mine": r.user_id == current_user.id,
        })

    return {
        "id": thread.id, "title": thread.title, "content": thread.content,
        "video_id": thread.video_id, "is_resolved": thread.is_resolved,
        "created_at": thread.created_at.isoformat() if thread.created_at else "",
        "author": {
            "id": thread.user_id,
            "name": author.full_name if author else "Unknown",
            "role": author.role.value if author and hasattr(author.role, 'value') else "",
            "initials": author.full_name[:1].upper() if author else "?",
        },
        "is_mine": thread.user_id == current_user.id,
        "replies": replies,
    }


@router.post("/threads/{thread_id}/reply", response_model=dict)
async def reply_to_thread(
    thread_id: int,
    data: ReplyCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add a reply to a discussion thread"""
    thread = db.query(DiscussionThread).filter(DiscussionThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if len(data.content.strip()) < 3:
        raise HTTPException(status_code=400, detail="Reply too short")

    reply = DiscussionReply(
        thread_id=thread_id, user_id=current_user.id, content=data.content.strip()
    )
    db.add(reply)
    thread.reply_count += 1
    db.commit()
    db.refresh(reply)

    u = current_user
    return {
        "id": reply.id, "content": reply.content,
        "is_verified": False, "like_count": 0,
        "created_at": reply.created_at.isoformat() if reply.created_at else "",
        "author": {
            "id": u.id, "name": u.full_name,
            "role": u.role.value if hasattr(u.role, 'value') else str(u.role),
            "initials": u.full_name[:1].upper(),
        },
        "is_mine": True,
    }


@router.post("/replies/{reply_id}/verify", response_model=dict)
async def verify_reply(
    reply_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Lecturer marks a reply as the verified correct answer"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role not in ["lecturer", "admin"]:
        raise HTTPException(status_code=403, detail="Only lecturers can verify answers")

    reply = db.query(DiscussionReply).filter(DiscussionReply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")

    reply.is_verified = not reply.is_verified

    # Mark thread as resolved when a verified answer exists
    thread = db.query(DiscussionThread).filter(DiscussionThread.id == reply.thread_id).first()
    if thread:
        thread.is_resolved = reply.is_verified
        thread.verified_answer_id = reply_id if reply.is_verified else None

    db.commit()
    return {"is_verified": reply.is_verified, "message": "Answer verified" if reply.is_verified else "Verification removed"}


@router.post("/replies/{reply_id}/like", response_model=dict)
async def like_reply(
    reply_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    reply = db.query(DiscussionReply).filter(DiscussionReply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    reply.like_count += 1
    db.commit()
    return {"like_count": reply.like_count}


# ─── Leaderboard ─────────────────────────────────────────────────────────────
@router.get("/leaderboard", response_model=dict)
async def get_leaderboard(
    course_id: Optional[int] = Query(None),
    period: str = Query("all_time"),   # all_time | this_week | this_month
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Leaderboard ranked by:
    - Videos completed (watch_percentage >= 90%)
    - Quiz scores (average)
    - Study streak
    Combined into a learning score.
    """
    from datetime import date, timedelta
    today = date.today()

    if period == "this_week":
        start_date = today - timedelta(days=7)
    elif period == "this_month":
        start_date = today - timedelta(days=30)
    else:
        start_date = None

    # Get all students
    from app.models.user import UserRole as UR
    students = db.query(User).filter(
        User.role == UR.STUDENT, User.is_active == True
    ).all()

    board = []
    for student in students:
        uid = student.id

        # Completions
        q = db.query(func.count(UserVideoInteraction.id)).filter(
            UserVideoInteraction.user_id == uid,
            UserVideoInteraction.interaction_type == 'view',
            UserVideoInteraction.watch_percentage >= 90,
        )
        if start_date:
            q = q.filter(func.date(UserVideoInteraction.created_at) >= start_date)
        completions = q.scalar() or 0

        # Avg quiz score
        qa = db.query(func.avg(QuizAttempt.score)).filter(QuizAttempt.user_id == uid)
        if start_date:
            qa = qa.filter(func.date(QuizAttempt.completed_at) >= start_date)
        avg_quiz = float(qa.scalar() or 0)

        # Streak
        streak = db.query(LearningStreak).filter(LearningStreak.user_id == uid).first()
        streak_days = streak.current_streak if streak else 0

        # Learning score formula
        score = (completions * 10) + (avg_quiz * 0.5) + (streak_days * 2)

        if score == 0 and completions == 0:
            continue

        board.append({
            "user_id": uid,
            "name": student.full_name,
            "department": student.department or "",
            "initials": student.full_name[:1].upper() if student.full_name else "?",
            "completions": completions,
            "avg_quiz_score": round(avg_quiz, 1),
            "streak_days": streak_days,
            "learning_score": round(score, 1),
            "is_me": uid == current_user.id,
        })

    board.sort(key=lambda x: x["learning_score"], reverse=True)

    # Add rank
    for i, entry in enumerate(board):
        entry["rank"] = i + 1
        if i == 0: entry["medal"] = "🥇"
        elif i == 1: entry["medal"] = "🥈"
        elif i == 2: entry["medal"] = "🥉"
        else: entry["medal"] = f"#{i+1}"

    # Find current user's position
    my_entry = next((e for e in board if e["is_me"]), None)

    return {
        "leaderboard": board[:50],
        "total_participants": len(board),
        "my_rank": my_entry["rank"] if my_entry else None,
        "my_score": my_entry["learning_score"] if my_entry else 0,
        "period": period,
    }
