from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base

class UserVideoInteraction(Base):
    __tablename__ = "user_video_interactions"
    __table_args__ = (
        UniqueConstraint('user_id', 'video_id', 'interaction_type', name='unique_user_video_interaction'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    interaction_type = Column(String(50), nullable=False)  # view, like, comment, share, complete, bookmark
    watch_percentage = Column(Float, default=0.0)
    watch_duration = Column(Integer, default=0)  # seconds watched
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="interactions")
    video = relationship("Video", back_populates="interactions")