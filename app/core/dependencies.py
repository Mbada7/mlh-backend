from typing import Optional, List
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from app.core.security import get_current_active_user
from app.services.cache_service import CacheService

# Singleton cache service instance
_cache_service = None

def get_cache_service() -> CacheService:
    """Dependency for cache service"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service

class RateLimiter:
    """Rate limiting dependency"""
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def __call__(self, request: Request, cache: CacheService = Depends(get_cache_service)):
        client_ip = request.client.host
        key = f"rate_limit:{client_ip}:{request.url.path}"
        
        current_count = await cache.get(key) or 0
        
        if current_count >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Max {self.max_requests} requests per {self.window_seconds} seconds."
            )
        
        await cache.set(key, current_count + 1, self.window_seconds)
        return True

class Pagination:
    """Pagination parameters dependency"""
    
    def __init__(
        self,
        skip: int = 0,
        limit: int = 20,
        max_limit: int = 100
    ):
        self.skip = skip
        self.limit = min(limit, max_limit)
        self.max_limit = max_limit

async def get_pagination(
    skip: int = 0,
    limit: int = 20
) -> Pagination:
    """Get pagination parameters"""
    return Pagination(skip=skip, limit=limit)

class RoleChecker:
    """Role-based access control dependency"""
    
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles
    
    async def __call__(self, current_user: User = Depends(get_current_active_user)):
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Required roles: {', '.join(self.allowed_roles)}"
            )
        return current_user

# Pre-configured role checkers
require_admin = RoleChecker(["admin"])
require_lecturer = RoleChecker(["lecturer", "admin"])
require_student = RoleChecker(["student", "lecturer", "admin"])

async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current user if authenticated, otherwise None"""
    try:
        from app.core.security import get_current_user
        return await get_current_user(request, db)
    except:
        return None

class DatabaseSessionManager:
    """Manage database sessions with context"""
    
    def __init__(self):
        self.db_gen = get_db()
    
    async def __aenter__(self):
        self.db = next(self.db_gen)
        return self.db
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

async def get_db_session() -> Session:
    """Get database session for background tasks"""
    db = next(get_db())
    try:
        yield db
    finally:
        db.close()

# Caching decorator
def cache_result(ttl: int = 300, key_prefix: str = ""):
    """Decorator to cache function results"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            cache = get_cache_service()
            
            # Generate cache key
            key_parts = [key_prefix, func.__name__]
            for arg in args:
                if isinstance(arg, (int, str, float)):
                    key_parts.append(str(arg))
            for k, v in kwargs.items():
                if isinstance(v, (int, str, float)):
                    key_parts.append(f"{k}:{v}")
            
            cache_key = ":".join(key_parts)
            
            # Try to get from cache
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache result
            if result is not None:
                await cache.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator