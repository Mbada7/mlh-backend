from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.quiz import Quiz, QuizQuestion, QuizAttempt

router = APIRouter(prefix="/quizzes", tags=["Quizzes"])


# ─── Schemas ──────────────────────────────────────────────────────────────────
class OptionSchema(BaseModel):
    id: str
    text: str


class QuestionCreate(BaseModel):
    question_text: str
    question_type: str = "mcq"   # mcq | true_false | short
    options: List[OptionSchema] = []
    correct_answer: str
    explanation: Optional[str] = None
    points: int = 1
    order_index: int = 0


class QuizCreate(BaseModel):
    video_id: int
    course_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    pass_mark: int = 50
    time_limit: Optional[int] = None
    max_attempts: int = 3
    questions: List[QuestionCreate]


class AnswerSubmit(BaseModel):
    answers: dict          # {question_id (str): answer_value}
    time_taken: Optional[int] = None


class QuestionResponse(BaseModel):
    id: int
    question_text: str
    question_type: str
    options: List[dict]
    points: int
    order_index: int
    # correct_answer is NOT returned to student until after submission

    class Config:
        from_attributes = True


class QuizResponse(BaseModel):
    id: int
    video_id: int
    course_id: Optional[int]
    title: str
    description: Optional[str]
    pass_mark: int
    time_limit: Optional[int]
    max_attempts: int
    is_active: bool
    question_count: int
    questions: List[QuestionResponse]

    class Config:
        from_attributes = True


class AttemptFeedback(BaseModel):
    question_id: int
    question_text: str
    your_answer: str
    correct_answer: str
    is_correct: bool
    explanation: Optional[str]
    points_earned: int
    points_possible: int


class AttemptResult(BaseModel):
    attempt_id: int
    quiz_id: int
    score: float
    passed: bool
    correct_count: int
    total_questions: int
    attempt_number: int
    feedback: List[AttemptFeedback]
    pass_mark: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/", response_model=dict)
async def create_quiz(
    data: QuizCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a quiz for a video (lecturers and admins only)"""
    role = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
    if role not in ["lecturer", "admin"]:
        raise HTTPException(status_code=403, detail="Only lecturers and admins can create quizzes")

    quiz = Quiz(
        video_id=data.video_id,
        course_id=data.course_id,
        title=data.title,
        description=data.description,
        pass_mark=data.pass_mark,
        time_limit=data.time_limit,
        max_attempts=data.max_attempts,
        created_by=current_user.id
    )
    db.add(quiz)
    db.flush()

    for q in data.questions:
        question = QuizQuestion(
            quiz_id=quiz.id,
            question_text=q.question_text,
            question_type=q.question_type,
            options=[o.model_dump() for o in q.options],
            correct_answer=q.correct_answer,
            explanation=q.explanation,
            points=q.points,
            order_index=q.order_index
        )
        db.add(question)

    db.commit()
    db.refresh(quiz)
    return {"id": quiz.id, "message": "Quiz created successfully"}


@router.get("/video/{video_id}", response_model=Optional[QuizResponse])
async def get_quiz_for_video(
    video_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get the active quiz for a video"""
    quiz = db.query(Quiz).filter(
        Quiz.video_id == video_id,
        Quiz.is_active == True
    ).first()

    if not quiz:
        return None

    questions = db.query(QuizQuestion).filter(
        QuizQuestion.quiz_id == quiz.id
    ).order_by(QuizQuestion.order_index).all()

    return {
        "id": quiz.id,
        "video_id": quiz.video_id,
        "course_id": quiz.course_id,
        "title": quiz.title,
        "description": quiz.description,
        "pass_mark": quiz.pass_mark,
        "time_limit": quiz.time_limit,
        "max_attempts": quiz.max_attempts,
        "is_active": quiz.is_active,
        "question_count": len(questions),
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": q.options,
                "points": q.points,
                "order_index": q.order_index,
            }
            for q in questions
        ]
    }


@router.post("/{quiz_id}/submit", response_model=AttemptResult)
async def submit_quiz(
    quiz_id: int,
    data: AnswerSubmit,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Submit quiz answers - auto-marks and returns detailed feedback"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    # Check attempt limit
    attempt_count = db.query(QuizAttempt).filter(
        QuizAttempt.quiz_id == quiz_id,
        QuizAttempt.user_id == current_user.id
    ).count()

    if attempt_count >= quiz.max_attempts:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum attempts ({quiz.max_attempts}) reached for this quiz"
        )

    questions = db.query(QuizQuestion).filter(
        QuizQuestion.quiz_id == quiz_id
    ).order_by(QuizQuestion.order_index).all()

    if not questions:
        raise HTTPException(status_code=400, detail="Quiz has no questions")

    # ─── Auto-marking ─────────────────────────────────────────────────────────
    total_points = sum(q.points for q in questions)
    earned_points = 0
    feedback_list = []
    feedback_dict = {}

    for q in questions:
        student_answer = str(data.answers.get(str(q.id), "")).strip().lower()
        correct = str(q.correct_answer).strip().lower()
        is_correct = student_answer == correct

        pts_earned = q.points if is_correct else 0
        earned_points += pts_earned

        fb = {
            "question_id": q.id,
            "question_text": q.question_text,
            "your_answer": str(data.answers.get(str(q.id), "Not answered")),
            "correct_answer": q.correct_answer,
            "is_correct": is_correct,
            "explanation": q.explanation,
            "points_earned": pts_earned,
            "points_possible": q.points,
        }
        feedback_list.append(fb)
        feedback_dict[str(q.id)] = fb

    score = round((earned_points / total_points) * 100, 1) if total_points > 0 else 0
    passed = score >= quiz.pass_mark

    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=current_user.id,
        answers=data.answers,
        score=score,
        passed=passed,
        time_taken=data.time_taken,
        attempt_number=attempt_count + 1,
        feedback=feedback_dict
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {
        "attempt_id": attempt.id,
        "quiz_id": quiz_id,
        "score": score,
        "passed": passed,
        "correct_count": sum(1 for f in feedback_list if f["is_correct"]),
        "total_questions": len(questions),
        "attempt_number": attempt.attempt_number,
        "feedback": feedback_list,
        "pass_mark": quiz.pass_mark,
    }


@router.get("/{quiz_id}/my-attempts", response_model=List[dict])
async def get_my_attempts(
    quiz_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get the current user's past attempts for a quiz"""
    attempts = db.query(QuizAttempt).filter(
        QuizAttempt.quiz_id == quiz_id,
        QuizAttempt.user_id == current_user.id
    ).order_by(QuizAttempt.completed_at.desc()).all()

    return [
        {
            "id": a.id,
            "score": a.score,
            "passed": a.passed,
            "attempt_number": a.attempt_number,
            "time_taken": a.time_taken,
            "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        }
        for a in attempts
    ]


@router.get("/my-results", response_model=List[dict])
async def get_all_my_results(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all quiz results for the current user"""
    attempts = db.query(QuizAttempt).filter(
        QuizAttempt.user_id == current_user.id
    ).order_by(QuizAttempt.completed_at.desc()).all()

    results = []
    for a in attempts:
        quiz = db.query(Quiz).filter(Quiz.id == a.quiz_id).first()
        results.append({
            "attempt_id": a.id,
            "quiz_id": a.quiz_id,
            "quiz_title": quiz.title if quiz else "Unknown",
            "video_id": quiz.video_id if quiz else None,
            "score": a.score,
            "passed": a.passed,
            "attempt_number": a.attempt_number,
            "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        })
    return results
