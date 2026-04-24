# app/services/notification_service.py
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from app.models.notification import Notification
from app.models.course import Course, Enrollment
from app.models.user import User
from app.models.video import Video


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    #  Create helpers                                                      #
    # ------------------------------------------------------------------ #

    def _create(self, user_id: int, type: str, title: str, message: str,
                video_id: Optional[int] = None, course_id: Optional[int] = None) -> Notification:
        n = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            video_id=video_id,
            course_id=course_id,
        )
        self.db.add(n)
        return n

    # ------------------------------------------------------------------ #
    #  Business triggers                                                   #
    # ------------------------------------------------------------------ #

    def notify_video_pending(self, video: Video):
        """Notify the course lecturer that a student video needs approval."""
        if not video.course_id:
            return
        course = self.db.query(Course).filter(Course.id == video.course_id).first()
        if not course:
            return
        uploader = self.db.query(User).filter(User.id == video.uploaded_by_user_id).first()
        uploader_name = uploader.full_name if uploader else "A student"

        self._create(
            user_id=course.lecturer_id,
            type="video_pending",
            title="New video awaiting approval",
            message=f"{uploader_name} uploaded \"{video.title}\" to {course.title}. Please review it.",
            video_id=video.id,
            course_id=course.id,
        )
        self.db.commit()

    def notify_video_approved(self, video: Video):
        """Notify the uploader their video was approved, and enrolled students of new content."""
        course = self.db.query(Course).filter(Course.id == video.course_id).first() if video.course_id else None

        # 1. Notify the uploader
        self._create(
            user_id=video.uploaded_by_user_id,
            type="video_approved",
            title="Your video was approved! 🎉",
            message=f"\"{video.title}\" has been approved and is now live"
                    + (f" in {course.title}" if course else "") + ".",
            video_id=video.id,
            course_id=video.course_id,
        )

        # 2. Notify enrolled students (excluding the uploader)
        if course:
            enrollments = self.db.query(Enrollment).filter(
                Enrollment.course_id == course.id,
                Enrollment.user_id != video.uploaded_by_user_id,
            ).all()
            for enr in enrollments:
                self._create(
                    user_id=enr.user_id,
                    type="new_course_video",
                    title=f"New video in {course.title}",
                    message=f"\"{video.title}\" has just been added to {course.title}.",
                    video_id=video.id,
                    course_id=course.id,
                )

        self.db.commit()

    def notify_video_rejected(self, video: Video, reason: Optional[str] = None):
        """Notify the uploader their video was rejected."""
        msg = f"\"{video.title}\" was not approved."
        if reason:
            msg += f" Reason: {reason}"
        self._create(
            user_id=video.uploaded_by_user_id,
            type="video_rejected",
            title="Video not approved",
            message=msg,
            video_id=video.id,
            course_id=video.course_id,
        )
        self.db.commit()

    def notify_lecturer_video_uploaded(self, video: Video):
        """
        When a lecturer (auto-approved) uploads to a course, notify enrolled students.
        """
        if not video.course_id:
            return
        course = self.db.query(Course).filter(Course.id == video.course_id).first()
        if not course:
            return
        enrollments = self.db.query(Enrollment).filter(
            Enrollment.course_id == course.id,
            Enrollment.user_id != video.uploaded_by_user_id,
        ).all()
        for enr in enrollments:
            self._create(
                user_id=enr.user_id,
                type="new_course_video",
                title=f"New video in {course.title}",
                message=f"\"{video.title}\" has been uploaded to {course.title}.",
                video_id=video.id,
                course_id=course.id,
            )
        self.db.commit()

    # ------------------------------------------------------------------ #
    #  Query helpers                                                       #
    # ------------------------------------------------------------------ #

    def get_user_notifications(self, user_id: int, skip: int = 0,
                               limit: int = 50, unread_only: bool = False) -> List[Notification]:
        q = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            q = q.filter(Notification.is_read == False)
        return q.order_by(desc(Notification.created_at)).offset(skip).limit(limit).all()

    def get_unread_count(self, user_id: int) -> int:
        return self.db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
        ).count()

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        n = self.db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        ).first()
        if n:
            n.is_read = True
            self.db.commit()
            return True
        return False

    def mark_all_read(self, user_id: int):
        self.db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
        ).update({"is_read": True})
        self.db.commit()
