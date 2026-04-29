from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    pass_mark = Column(Integer, default=50)        # percentage
    time_limit = Column(Integer, nullable=True)    # seconds, None = no limit
    max_attempts = Column(Integer, default=3)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    questions = relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan")
    attempts = relationship("QuizAttempt", back_populates="quiz")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), default="mcq")   # mcq | true_false | short
    options = Column(JSON, default=list)                 # [{"id": "a", "text": "..."}]
    correct_answer = Column(String(255), nullable=False)  # option id or text
    explanation = Column(Text, nullable=True)
    points = Column(Integer, default=1)
    order_index = Column(Integer, default=0)

    quiz = relationship("Quiz", back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    answers = Column(JSON, default=dict)             # {question_id: answer}
    score = Column(Float, default=0)                 # percentage 0-100
    passed = Column(Boolean, default=False)
    time_taken = Column(Integer, nullable=True)      # seconds
    attempt_number = Column(Integer, default=1)
    feedback = Column(JSON, default=dict)            # per-question feedback
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

    quiz = relationship("Quiz", back_populates="attempts")


class VideoDownload(Base):
    __tablename__ = "video_downloads"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    downloaded_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)   # 7 days
    file_path = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
