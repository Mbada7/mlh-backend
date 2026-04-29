from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Date, JSON, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class LearningStreak(Base):
    """Tracks daily login/study streaks per user"""
    __tablename__ = "learning_streaks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    current_streak = Column(Integer, default=0)       # consecutive days
    longest_streak = Column(Integer, default=0)
    last_activity_date = Column(Date, nullable=True)
    total_study_days = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VideoDropOff(Base):
    """Tracks at what percentage students stop watching a video"""
    __tablename__ = "video_drop_offs"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    drop_off_percentage = Column(Float, default=0.0)  # 0-100
    session_date = Column(Date, server_default=func.current_date())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DailyLearningLog(Base):
    """Records daily study minutes per user"""
    __tablename__ = "daily_learning_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    log_date = Column(Date, nullable=False)
    minutes_studied = Column(Integer, default=0)
    videos_watched = Column(Integer, default=0)
    quizzes_taken = Column(Integer, default=0)
    avg_quiz_score = Column(Float, default=0.0)
