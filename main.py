from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
from app.core.config import settings
from app.core.database import init_db
from app.models import notification, quiz  # noqa
from app.models import analytics, peer_learning  # noqa — new models

try:
    from app.api.v1 import auth, users, videos, courses, feed, recommendations, notifications
    from app.api.v1 import quizzes, downloads, admin
    from app.api.v1 import analytics as analytics_router        # NEW
    from app.api.v1 import learning_path                        # NEW
    from app.api.v1 import peer_learning as peer_router         # NEW
except ImportError as e:
    print(f"Import error: {e}")
    from fastapi import APIRouter
    auth = users = videos = courses = feed = recommendations = notifications = APIRouter()
    quizzes = downloads = admin = APIRouter()
    analytics_router = learning_path = peer_router = APIRouter()

os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting MSU LearningHub API v3.0...")
    init_db()
    print("Database ready")
    yield

app = FastAPI(title="MSU LearningHub API", version="3.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.LOCAL_STORAGE_PATH), name="uploads")
app.mount("/uploads/videos", StaticFiles(directory=os.path.join(settings.LOCAL_STORAGE_PATH, "videos")), name="videos")
app.mount("/uploads/thumbnails", StaticFiles(directory=os.path.join(settings.LOCAL_STORAGE_PATH, "thumbnails")), name="thumbnails")

try:
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(videos.router, prefix="/api/v1")
    app.include_router(courses.router, prefix="/api/v1")
    app.include_router(feed.router, prefix="/api/v1")
    app.include_router(recommendations.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(quizzes.router, prefix="/api/v1")
    app.include_router(downloads.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(analytics_router.router, prefix="/api/v1")   # NEW
    app.include_router(learning_path.router, prefix="/api/v1")      # NEW
    app.include_router(peer_router.router, prefix="/api/v1")        # NEW
except Exception as e:
    print(f"Router error: {e}")

@app.get("/")
async def root():
    return {"message": "MSU LearningHub API v3.0", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "healthy", "storage": os.path.exists(settings.LOCAL_STORAGE_PATH)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
