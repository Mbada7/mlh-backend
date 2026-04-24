from sqlalchemy import Column, Integer, Float, DateTime, String, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from pgvector.sqlalchemy import Vector  # You'll need: pip install pgvector

class UserEmbedding(Base):
    """Stores user feature vectors for recommendation models"""
    __tablename__ = "user_embeddings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    embedding_vector = Column(Vector(128))  # 128-dimensional embedding
    model_version = Column(String(50), default="v1.0")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Index for similarity search
    __table_args__ = (
        Index('idx_user_embedding_vector', embedding_vector, postgresql_using='ivfflat'),
    )
    
    user = relationship("User", backref="embedding")

class VideoEmbedding(Base):
    """Stores video feature vectors for content-based recommendations"""
    __tablename__ = "video_embeddings"
    
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), unique=True, nullable=False)
    embedding_vector = Column(Vector(128))
    text_embedding = Column(Vector(64))  # For title/description similarity
    visual_embedding = Column(Vector(64))  # For thumbnail/content similarity
    model_version = Column(String(50), default="v1.0")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_video_embedding_vector', embedding_vector, postgresql_using='ivfflat'),
    )
    
    video = relationship("Video", backref="embedding")

class RecommendationCache(Base):
    """Cache for pre-computed recommendations"""
    __tablename__ = "recommendation_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recommendation_type = Column(String(50))  # 'personalized', 'trending', 'similar'
    video_ids = Column(JSON, default=list)
    scores = Column(JSON, default=list)  # Confidence scores for each recommendation
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", backref="recommendation_cache")
    
    __table_args__ = (
        Index('idx_rec_cache_user_type', 'user_id', 'recommendation_type'),
        Index('idx_rec_cache_expires', 'expires_at'),
    )

class RecommendationFeedback(Base):
    """Stores user feedback on recommendations for model improvement"""
    __tablename__ = "recommendation_feedback"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    recommendation_id = Column(String(255))  # ID of the recommendation session
    position = Column(Integer)  # Position in feed (1-20)
    clicked = Column(Integer, default=0)  # Whether user clicked on recommendation
    watched_duration = Column(Integer, default=0)  # How long they watched
    liked = Column(Integer, default=0)  # Whether they liked the video
    feedback_score = Column(Float, default=0.0)  # Implicit feedback score
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", backref="recommendation_feedback")
    video = relationship("Video", backref="recommendation_feedback")
    
    __table_args__ = (
        Index('idx_rec_feedback_user', 'user_id'),
        Index('idx_rec_feedback_video', 'video_id'),
        Index('idx_rec_feedback_recommendation', 'recommendation_id'),
    )

class ModelMetrics(Base):
    """Tracks recommendation model performance metrics"""
    __tablename__ = "model_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50), nullable=False)
    metric_name = Column(String(50), nullable=False)  # precision@10, recall@10, ndcg@10
    metric_value = Column(Float, nullable=False)
    test_size = Column(Integer, default=0)
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index('idx_model_metrics_name_version', 'model_name', 'model_version'),
    )