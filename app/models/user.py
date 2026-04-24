from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base

class UserRole(str, enum.Enum):
    STUDENT = "student"
    LECTURER = "lecturer"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.STUDENT)
    profile_picture = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    student_id = Column(String(50), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    videos = relationship("Video", back_populates="uploader", foreign_keys="Video.uploaded_by_user_id")
    comments = relationship("Comment", back_populates="user")
    interactions = relationship("UserVideoInteraction", back_populates="user")
    enrolled_courses = relationship("Enrollment", back_populates="user")
    teaching_courses = relationship("Course", back_populates="lecturer")