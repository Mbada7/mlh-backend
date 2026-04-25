# app/services/video_service.py
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from fastapi import HTTPException, status, UploadFile
from typing import List, Optional, Tuple
import os
import uuid
import shutil
import subprocess
from datetime import datetime, date
from app.models.video import Video, Comment
from app.models.user import User
from app.models.interaction import UserVideoInteraction
from app.models.course import Course, Enrollment
from app.core.config import settings

class VideoService:
    def __init__(self, db: Session):
        self.db = db
    
    def upload_video(
        self, 
        user_id: int, 
        file: UploadFile, 
        title: str, 
        description: str, 
        course_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        user_role: str = "student"
    ) -> Video:
        """
        Upload a new video with validation and thumbnail generation
        """
        # Normalise role
        if hasattr(user_role, 'value'):
            user_role = user_role.value
        else:
            user_role = str(user_role)
        # Validate file type
        file_extension = file.filename.split('.')[-1].lower()
        if file_extension not in settings.ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed. Allowed: {', '.join(settings.ALLOWED_VIDEO_EXTENSIONS)}"
            )
        
        # Validate file size (max 100MB)
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > settings.MAX_VIDEO_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Max size: {settings.MAX_VIDEO_SIZE // (1024*1024)}MB"
            )
        
        # Get user info
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        # Validate course permissions
        if course_id:
            course = self.db.query(Course).filter(Course.id == course_id).first()
            if not course:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
            
            if user_role == "lecturer" or user_role == "admin":
                if course.lecturer_id != user_id and user_role != "admin":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN, 
                        detail="You can only upload to courses you teach"
                    )
            else:
                enrollment = self.db.query(Enrollment).filter(
                    Enrollment.user_id == user_id,
                    Enrollment.course_id == course_id
                ).first()
                
                if not enrollment:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN, 
                        detail="You must be enrolled in this course to upload videos"
                    )
                
                today = date.today()
                daily_count = self.db.query(Video).filter(
                    Video.uploaded_by_user_id == user_id,
                    Video.course_id == course_id,
                    func.date(Video.created_at) == today
                ).count()
                
                if daily_count >= 5:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Daily upload limit reached (2 videos per course)"
                    )
        else:
            if user_role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Videos must be uploaded to a specific course"
                )
        
        # Save file and get absolute path
        absolute_path, video_duration = self._save_video_file(file, user_id)
        
        # Parse tags
        tag_list = tags or []
        
        # Generate thumbnail using absolute path
        thumbnail_path = self._generate_thumbnail(absolute_path, user_id)
        
        # Create video record with absolute paths
        video = Video(
            title=title,
            description=description,
            video_url=absolute_path,  # Store absolute path
            thumbnail_url=thumbnail_path,  # Store absolute thumbnail path
            duration=video_duration,
            course_id=course_id,
            uploaded_by_user_id=user_id,
            tags=tag_list,
            file_size=file_size,
            is_published=True if user_role != "student" else False,
            approval_status="approved" if user_role != "student" else "pending"
        )
        
        self.db.add(video)
        self.db.commit()
        self.db.refresh(video)

        # ── Notifications ──────────────────────────────────────────────
        try:
            from app.services.notification_service import NotificationService
            notif_svc = NotificationService(self.db)
            if video.approval_status == "pending":
                # Student upload → alert the course lecturer
                notif_svc.notify_video_pending(video)
            else:
                # Lecturer/admin upload → auto-approved, alert enrolled students
                notif_svc.notify_lecturer_video_uploaded(video)
        except Exception as e:
            print(f"Notification error (non-fatal): {e}")

        return video
    
    def _save_video_file(self, file: UploadFile, user_id: int) -> Tuple[str, Optional[int]]:
        """Save video file to storage and return absolute path and duration"""
        # Get absolute upload directory
        base_upload_dir = settings.ABSOLUTE_STORAGE_PATH
        upload_dir = os.path.join(base_upload_dir, "videos", str(user_id))
        os.makedirs(upload_dir, exist_ok=True)
        
        file_extension = file.filename.split('.')[-1]
        filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Absolute path on your computer
        absolute_path = os.path.join(upload_dir, filename)
        
        # Save file
        try:
            with open(absolute_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save video file: {str(e)}"
            )
        
        # Get duration
        duration = self._get_video_duration(absolute_path)
        
        return absolute_path, duration

    def _get_video_duration(self, video_path: str) -> Optional[int]:
        """Get video duration in seconds using ffprobe"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return int(float(result.stdout.strip()))
        except Exception as e:
            print(f"Error getting video duration: {e}")
        return None
    
    def _generate_thumbnail(self, absolute_video_path: str, user_id: int) -> Optional[str]:
        """Generate thumbnail from video at 1 second mark"""
        try:
            # Check if video file exists
            if not os.path.exists(absolute_video_path):
                print(f"Video file not found: {absolute_video_path}")
                return None
            
            # Create thumbnail directory
            base_upload_dir = settings.ABSOLUTE_STORAGE_PATH
            thumbnail_dir = os.path.join(base_upload_dir, "thumbnails", str(user_id))
            os.makedirs(thumbnail_dir, exist_ok=True)
            
            thumbnail_filename = f"{uuid.uuid4().hex[:8]}.jpg"
            thumbnail_absolute_path = os.path.join(thumbnail_dir, thumbnail_filename)
            
            # Use ffmpeg to extract frame at 1 second
            cmd = [
                'ffmpeg',
                '-i', absolute_video_path,
                '-ss', '00:00:01',
                '-vframes', '1',
                '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2',
                '-q:v', '2',
                '-y',
                thumbnail_absolute_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(thumbnail_absolute_path) and os.path.getsize(thumbnail_absolute_path) > 0:
                return thumbnail_absolute_path
            else:
                print(f"Thumbnail generation failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            print("Thumbnail generation timed out")
            return None
        except Exception as e:
            print(f"Error generating thumbnail: {e}")
            return None
    
    def get_video(self, video_id: int, user_id: Optional[int] = None,
                  user_role: str = "student") -> Video:
        """Get video by ID with view tracking.

        Visibility rules
        ─────────────────
        published     → everyone can see
        unpublished   → only the uploader OR the course lecturer (for preview)
        """
        # Normalise role — handles both plain str and UserRole enum
        if hasattr(user_role, 'value'):
            user_role = user_role.value
        else:
            user_role = str(user_role)
        video = self.db.query(Video).filter(Video.id == video_id).first()

        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

        # If the video is not published, only allow the uploader or the course lecturer
        if not video.is_published:
            if user_id is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
            is_uploader = video.uploaded_by_user_id == user_id
            is_admin = user_role == "admin"
            is_course_lecturer = False
            if video.course_id:
                from app.models.course import Course
                course = self.db.query(Course).filter(Course.id == video.course_id).first()
                is_course_lecturer = course is not None and course.lecturer_id == user_id
            if not (is_uploader or is_admin or is_course_lecturer):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        if user_id:
            one_hour_ago = datetime.utcnow()
            recent_view = self.db.query(UserVideoInteraction).filter(
                UserVideoInteraction.user_id == user_id,
                UserVideoInteraction.video_id == video_id,
                UserVideoInteraction.interaction_type == "view",
                UserVideoInteraction.created_at >= one_hour_ago
            ).first()
            
            if not recent_view:
                self._record_interaction(user_id, video_id, "view")
                video.view_count += 1
                self.db.commit()
        
        return video
    
    def get_video_with_details(self, video_id: int, user_id: Optional[int] = None,
                               user_role: str = "student") -> dict:
        """Get video with additional details - returns streaming URLs"""
        video = self.get_video(video_id, user_id, user_role)
        
        uploader = self.db.query(User).filter(User.id == video.uploaded_by_user_id).first()
        
        user_liked = False
        user_bookmarked = False
        user_watch_percentage = 0
        
        if user_id:
            liked = self.db.query(UserVideoInteraction).filter(
                UserVideoInteraction.user_id == user_id,
                UserVideoInteraction.video_id == video_id,
                UserVideoInteraction.interaction_type == "like"
            ).first()
            user_liked = liked is not None
            
            bookmarked = self.db.query(UserVideoInteraction).filter(
                UserVideoInteraction.user_id == user_id,
                UserVideoInteraction.video_id == video_id,
                UserVideoInteraction.interaction_type == "bookmark"
            ).first()
            user_bookmarked = bookmarked is not None
            
            watch = self.db.query(UserVideoInteraction).filter(
                UserVideoInteraction.user_id == user_id,
                UserVideoInteraction.video_id == video_id,
                UserVideoInteraction.interaction_type == "view"
            ).first()
            if watch:
                user_watch_percentage = watch.watch_percentage
        
        # Return streaming URLs instead of file paths
        from app.core.config import settings
        base_url = settings.BACKEND_URL.rstrip('/')
        
        return {
            "id": video.id,
            "title": video.title,
            "description": video.description,
            "video_url": f"{base_url}/api/v1/videos/stream/{video_id}",
            "thumbnail_url": f"{base_url}/api/v1/videos/thumbnail/{video_id}" if video.thumbnail_url else None,
            "duration": video.duration,
            "view_count": video.view_count,
            "like_count": video.like_count,
            "comment_count": video.comment_count,
            "share_count": video.share_count,
            "course_id": video.course_id,
            "uploaded_by_user_id": video.uploaded_by_user_id,
            "uploader_name": uploader.full_name if uploader else "Unknown",
            "uploader_profile_picture": uploader.profile_picture if uploader else None,
            "tags": video.tags or [],
            "is_published": video.is_published,
            "is_featured": video.is_featured,
            "created_at": video.created_at,
            "user_liked": user_liked,
            "user_bookmarked": user_bookmarked,
            "user_watch_percentage": user_watch_percentage,
            "approval_status": video.approval_status,
            "rejection_reason": video.rejection_reason,
        }
    
    def _record_interaction(self, user_id: int, video_id: int, interaction_type: str, watch_percentage: float = 0.0, watch_duration: int = 0):
        """Record user interaction with video"""
        existing = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.video_id == video_id,
            UserVideoInteraction.interaction_type == interaction_type
        ).first()
        
        if existing and interaction_type in ["view", "like"]:
            return existing
        
        interaction = UserVideoInteraction(
            user_id=user_id,
            video_id=video_id,
            interaction_type=interaction_type,
            watch_percentage=watch_percentage,
            watch_duration=watch_duration
        )
        
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    def like_video(self, video_id: int, user_id: int):
        """Like or unlike a video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        existing_like = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.video_id == video_id,
            UserVideoInteraction.interaction_type == "like"
        ).first()
        
        if existing_like:
            self.db.delete(existing_like)
            video.like_count = max(0, video.like_count - 1)
            self.db.commit()
            return {"liked": False, "like_count": video.like_count}
        else:
            like = UserVideoInteraction(
                user_id=user_id,
                video_id=video_id,
                interaction_type="like"
            )
            self.db.add(like)
            video.like_count += 1
            self.db.commit()
            return {"liked": True, "like_count": video.like_count}
    
    def bookmark_video(self, video_id: int, user_id: int):
        """Bookmark or unbookmark a video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        existing_bookmark = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.video_id == video_id,
            UserVideoInteraction.interaction_type == "bookmark"
        ).first()
        
        if existing_bookmark:
            self.db.delete(existing_bookmark)
            self.db.commit()
            return {"bookmarked": False}
        else:
            bookmark = UserVideoInteraction(
                user_id=user_id,
                video_id=video_id,
                interaction_type="bookmark"
            )
            self.db.add(bookmark)
            self.db.commit()
            return {"bookmarked": True}
    
    def update_watch_progress(self, video_id: int, user_id: int, watch_percentage: float, watch_duration: int):
        """Update user's watch progress for a video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        watch_interaction = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.video_id == video_id,
            UserVideoInteraction.interaction_type == "view"
        ).first()
        
        if watch_interaction:
            watch_interaction.watch_percentage = max(watch_interaction.watch_percentage, watch_percentage)
            watch_interaction.watch_duration = max(watch_interaction.watch_duration, watch_duration)
        else:
            watch_interaction = UserVideoInteraction(
                user_id=user_id,
                video_id=video_id,
                interaction_type="view",
                watch_percentage=watch_percentage,
                watch_duration=watch_duration
            )
            self.db.add(watch_interaction)
        
        if watch_percentage >= 0.9:
            completion = self.db.query(UserVideoInteraction).filter(
                UserVideoInteraction.user_id == user_id,
                UserVideoInteraction.video_id == video_id,
                UserVideoInteraction.interaction_type == "complete"
            ).first()
            
            if not completion:
                complete_interaction = UserVideoInteraction(
                    user_id=user_id,
                    video_id=video_id,
                    interaction_type="complete",
                    watch_percentage=watch_percentage,
                    watch_duration=watch_duration
                )
                self.db.add(complete_interaction)
        
        self.db.commit()
        
        return {"status": "progress_updated", "watch_percentage": watch_percentage}
    
    def add_comment(self, video_id: int, user_id: int, content: str, parent_comment_id: Optional[int] = None) -> Comment:
        """Add comment to video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        if len(content.strip()) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comment cannot be empty")
        
        if len(content) > 1000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comment too long (max 1000 characters)")
        
        comment = Comment(
            content=content,
            user_id=user_id,
            video_id=video_id,
            parent_comment_id=parent_comment_id
        )
        
        self.db.add(comment)
        video.comment_count += 1
        self.db.commit()
        self.db.refresh(comment)
        
        user = self.db.query(User).filter(User.id == user_id).first()

        # Return a dict so Pydantic gets replies=[] instead of None
        # (the ORM relationship is not eagerly loaded, so replies would be None
        #  and cause a ResponseValidationError: "Input should be a valid list")
        return {
            "id": comment.id,
            "content": comment.content,
            "user_id": comment.user_id,
            "username": user.username if user else "Unknown",
            "user_profile_picture": user.profile_picture if user else None,
            "like_count": comment.like_count,
            "created_at": comment.created_at,
            "replies": [],
        }
    
    def get_comments(self, video_id: int, skip: int = 0, limit: int = 50) -> List[dict]:
        """Get comments for video with user info"""
        comments = self.db.query(Comment).filter(
            Comment.video_id == video_id,
            Comment.parent_comment_id == None
        ).order_by(desc(Comment.created_at)).offset(skip).limit(limit).all()
        
        result = []
        for comment in comments:
            user = self.db.query(User).filter(User.id == comment.user_id).first()
            
            replies = self.db.query(Comment).filter(
                Comment.parent_comment_id == comment.id
            ).order_by(Comment.created_at).all()
            
            reply_list = []
            for reply in replies:
                reply_user = self.db.query(User).filter(User.id == reply.user_id).first()
                reply_list.append({
                    "id": reply.id,
                    "content": reply.content,
                    "user_id": reply.user_id,
                    "username": reply_user.username if reply_user else "Unknown",
                    "user_profile_picture": reply_user.profile_picture if reply_user else None,
                    "like_count": reply.like_count,
                    "created_at": reply.created_at,
                    "replies": []
                })
            
            result.append({
                "id": comment.id,
                "content": comment.content,
                "user_id": comment.user_id,
                "username": user.username if user else "Unknown",
                "user_profile_picture": user.profile_picture if user else None,
                "like_count": comment.like_count,
                "created_at": comment.created_at,
                "replies": reply_list
            })
        
        return result
    
    def delete_comment(self, comment_id: int, user_id: int, user_role: str) -> dict:
        """Delete a comment"""
        comment = self.db.query(Comment).filter(Comment.id == comment_id).first()
        if not comment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        
        video = self.db.query(Video).filter(Video.id == comment.video_id).first()
        
        is_owner = comment.user_id == user_id
        is_admin = user_role == "admin"
        
        if not (is_owner or is_admin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete this comment")
        
        self.db.delete(comment)
        if video:
            video.comment_count = max(0, video.comment_count - 1)
        
        self.db.commit()
        
        return {"message": "Comment deleted successfully"}
    
    def get_user_videos(self, user_id: int, skip: int = 0, limit: int = 50) -> List[Video]:
        """Get all videos uploaded by a user (including pending ones)"""
        videos = self.db.query(Video).filter(
            Video.uploaded_by_user_id == user_id
            # DO NOT filter by is_published — student uploads are pending (is_published=False)
            # and should still appear in the uploader's own My Videos list
        ).order_by(desc(Video.created_at)).offset(skip).limit(limit).all()
        
        return videos
    
    def update_video(self, video_id: int, user_id: int, user_role: str, title: Optional[str] = None, 
                     description: Optional[str] = None, tags: Optional[List[str]] = None,
                     is_published: Optional[bool] = None) -> Video:
        """Update video metadata"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        is_owner = video.uploaded_by_user_id == user_id
        is_admin = user_role == "admin"
        
        if not (is_owner or is_admin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit this video")
        
        if title is not None:
            video.title = title
        if description is not None:
            video.description = description
        if tags is not None:
            video.tags = tags
        if is_published is not None and (is_admin or video.approval_status == "approved"):
            video.is_published = is_published
        
        self.db.commit()
        self.db.refresh(video)
        
        return video
    
    def delete_video(self, video_id: int, user_id: int, user_role: str) -> dict:
        """Delete a video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        is_owner = video.uploaded_by_user_id == user_id
        is_admin = user_role == "admin"
        
        if not (is_owner or is_admin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete this video")
        
        try:
            if os.path.exists(video.video_url):
                os.remove(video.video_url)
            if video.thumbnail_url and os.path.exists(video.thumbnail_url):
                os.remove(video.thumbnail_url)
        except Exception as e:
            print(f"Error deleting video file: {e}")
        
        self.db.delete(video)
        self.db.commit()
        
        return {"message": "Video deleted successfully"}
    
    def approve_student_video(self, video_id: int, lecturer_id: int, approved: bool, rejection_reason: Optional[str] = None) -> dict:
        """Approve or reject student video"""
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
        
        course = self.db.query(Course).filter(Course.id == video.course_id).first()
        if not course or course.lecturer_id != lecturer_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't teach this course")
        
        if approved:
            video.is_published = True
            video.approval_status = "approved"
            video.rejection_reason = None
        else:
            video.is_published = False
            video.approval_status = "rejected"
            video.rejection_reason = rejection_reason

        self.db.commit()

        # ── Notifications ──────────────────────────────────────────────
        try:
            from app.services.notification_service import NotificationService
            notif_svc = NotificationService(self.db)
            if approved:
                notif_svc.notify_video_approved(video)
            else:
                notif_svc.notify_video_rejected(video, rejection_reason)
        except Exception as e:
            print(f"Notification error (non-fatal): {e}")

        return {"message": "Video approved" if approved else "Video rejected", "status": video.approval_status}
    
    def get_pending_videos(self, lecturer_id: int, skip: int = 0, limit: int = 50) -> List[Video]:
        """Get pending videos for lecturer's courses.
        
        Shows ALL pending videos in courses this lecturer teaches.
        Also shows pending videos with no course (uploaded by students without a course link)
        if the caller is an admin (lecturer_id=0 used as sentinel).
        """
        from app.models.user import User as UserModel
        lecturer = self.db.query(UserModel).filter(UserModel.id == lecturer_id).first()
        role = ""
        if lecturer:
            role = lecturer.role.value if hasattr(lecturer.role, "value") else str(lecturer.role)

        if role == "admin":
            # Admins see all pending videos
            pending_videos = self.db.query(Video).filter(
                Video.approval_status == "pending",
                Video.is_published == False  # noqa: E712
            ).order_by(Video.created_at).offset(skip).limit(limit).all()
            return pending_videos

        # Lecturers: find their courses
        courses = self.db.query(Course).filter(Course.lecturer_id == lecturer_id).all()
        course_ids = [c.id for c in courses]

        if not course_ids:
            return []

        pending_videos = self.db.query(Video).filter(
            Video.course_id.in_(course_ids),
            Video.approval_status == "pending",
            Video.is_published == False  # noqa: E712
        ).order_by(Video.created_at).offset(skip).limit(limit).all()

        return pending_videos