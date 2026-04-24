from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime
from app.models.user import User
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token
from app.schemas.user import UserCreate

class AuthService:
    def __init__(self, db: Session):
        self.db = db
    
    def register_user(self, user_data: UserCreate) -> User:
        # Check if user exists
        existing_user = self.db.query(User).filter(
            (User.email == user_data.email) | (User.username == user_data.username)
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email or username already registered"
            )
        
        # Create new user
        hashed_password = get_password_hash(user_data.password)
        db_user = User(
            email=user_data.email,
            username=user_data.username,
            full_name=user_data.full_name,
            hashed_password=hashed_password,
            role=user_data.role,
            department=user_data.department,
            student_id=user_data.student_id
        )
        
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        
        return db_user
    
    def authenticate_user(self, email: str, password: str) -> User:
        user = self.db.query(User).filter(User.email == email).first()
        
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account is deactivated"
            )
        
        # Update last login
        user.last_login = datetime.utcnow()
        self.db.commit()
        
        return user
    
    # def generate_tokens(self, user: User) -> dict:
    #     access_token = create_access_token(data={"sub": user.id, "email": user.email, "role": user.role})
    #     refresh_token = create_refresh_token(data={"sub": user.id})
        
    #     return {
    #         "access_token": access_token,
    #         "refresh_token": refresh_token,
    #         "token_type": "bearer"
    #     }
    def generate_tokens(self, user: User) -> dict:
        access_token = create_access_token(data={
            "sub": str(user.id),  # Convert to string
            "email": user.email, 
            "role": user.role
        })
        refresh_token = create_refresh_token(data={"sub": str(user.id)})  # Convert to string
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
