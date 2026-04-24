# app/core/config.py - Add ABSOLUTE_STORAGE_PATH property
import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:pos87tenfad94@localhost:5432/mlhdb")
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "20"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "40"))
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    
    # CORS
    ALLOWED_ORIGINS: List[str] = eval(os.getenv("ALLOWED_ORIGINS", '["http://localhost:3000", "http://localhost:8081"]'))
    
    # File Storage
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "local")
    LOCAL_STORAGE_PATH: str = os.getenv("LOCAL_STORAGE_PATH", "./uploads")
    MAX_VIDEO_SIZE: int = int(os.getenv("MAX_VIDEO_SIZE", "104857600"))
    ALLOWED_VIDEO_EXTENSIONS: List[str] = eval(os.getenv("ALLOWED_VIDEO_EXTENSIONS", '["mp4", "mov", "avi"]'))
    
    # ✅ Absolute storage path
    @property
    def ABSOLUTE_STORAGE_PATH(self) -> str:
        return os.path.abspath(self.LOCAL_STORAGE_PATH)
    
    # Backend URL
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    
    # ML Settings
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "128"))
    RECOMMENDATION_CACHE_TTL: int = int(os.getenv("RECOMMENDATION_CACHE_TTL", "300"))
    MODEL_UPDATE_INTERVAL_HOURS: int = int(os.getenv("MODEL_UPDATE_INTERVAL_HOURS", "6"))
    
    # Admin
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@msu.ac.zw")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "Admin123!")
    
    model_config = {"case_sensitive": True}

settings = Settings()