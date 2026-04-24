from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.core.security import decode_token
from app.schemas.user import UserCreate, UserLogin, Token, TokenRefresh, UserResponse
from app.services.auth_service import AuthService
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    auth_service = AuthService(db)
    user = auth_service.register_user(user_data)
    return user

@router.post("/login", response_model=Token)
async def login(
    login_data: UserLogin, 
    db: Session = Depends(get_db)
):
    """Login user and return tokens"""
    auth_service = AuthService(db)
    user = auth_service.authenticate_user(login_data.email, login_data.password)
    tokens = auth_service.generate_tokens(user)
    return tokens

@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,  # Add Request to access cookies
    refresh_data: Optional[TokenRefresh] = None,  # Make body optional
    db: Session = Depends(get_db)
):
    """Refresh access token - accepts token from body OR cookie"""
    
    # Try to get refresh token from request body first
    refresh_token = None
    if refresh_data and refresh_data.refresh_token:
        refresh_token = refresh_data.refresh_token
    
    # If not in body, try to get from cookie
    if not refresh_token:
        refresh_token = request.cookies.get("refresh_token")
    
    # If still no token, raise error
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Refresh token required in body or cookie"
        )
    
    try:
        # Decode and validate the refresh token
        payload = decode_token(refresh_token)
        
        # Check if this is actually a refresh token
        token_type = payload.get("type")
        if token_type != "refresh":  # Check without "and token_type"
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid token type - refresh token expected"
            )
        
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid token: missing user ID"
            )
        
        auth_service = AuthService(db)
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="User not found"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="User account is inactive"
            )
        
        # Generate new tokens
        tokens = auth_service.generate_tokens(user)
        return tokens
        
    except HTTPException:
        raise
    except Exception as e:
        # Log the error for debugging (optional)
        print(f"Refresh token error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid refresh token"
        )