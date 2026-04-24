# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
from app.core.config import settings
from app.core.database import init_db
# Import all models so SQLAlchemy creates tables on startup
from app.models import notification  # noqa: F401

# Import routers with error handling
try:
    from app.api.v1 import auth, users, videos, courses, feed, recommendations, notifications
except ImportError as e:
    print(f"Error importing routes: {e}")
    # Create dummy routers for missing ones
    from fastapi import APIRouter
    auth = APIRouter()
    users = APIRouter()
    videos = APIRouter()
    courses = APIRouter()
    feed = APIRouter()
    recommendations = APIRouter()

# Create uploads directory if not exists
os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up MSU LearningHub API...")
    init_db()
    print("Database initialized successfully")
    yield
    # Shutdown
    print("Shutting down...")

# Create FastAPI app
app = FastAPI(
    title="MSU LearningHub API",
    description="Backend API for MSU LearningHub - Interactive Learning through Short Educational Videos",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (uploaded videos)
os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.LOCAL_STORAGE_PATH), name="uploads")
app.mount("/uploads/videos", StaticFiles(directory=os.path.join(settings.LOCAL_STORAGE_PATH, "videos")), name="videos")
app.mount("/uploads/thumbnails", StaticFiles(directory=os.path.join(settings.LOCAL_STORAGE_PATH, "thumbnails")), name="thumbnails")

# Include routers only if they have routes
try:
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(videos.router, prefix="/api/v1")
    app.include_router(courses.router, prefix="/api/v1")
    app.include_router(feed.router, prefix="/api/v1")
    app.include_router(recommendations.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
except Exception as e:
    print(f"Error including routers: {e}")

@app.get("/")
async def root():
    return {
        "message": "Welcome to MSU LearningHub API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "storage": os.path.exists(settings.LOCAL_STORAGE_PATH)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )