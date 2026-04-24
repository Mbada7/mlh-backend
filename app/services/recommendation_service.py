# app/services/recommendation_service.py
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_
from typing import List
from datetime import datetime, timedelta
from app.models.video import Video
from app.models.interaction import UserVideoInteraction
from app.models.course import Enrollment, Course
from app.models.user import User

class RecommendationService:
    def __init__(self, db: Session):
        self.db = db
    
    async def get_personalized_feed(self, user_id: int, limit: int = 20) -> List[Video]:
        """Get personalized video feed for user"""
        
        # Get user's interaction history
        user_history = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id
        ).order_by(desc(UserVideoInteraction.created_at)).limit(100).all()
        
        # Cold start: user has few interactions
        if len(user_history) < 10:
            return await self._get_cold_start_recommendations(user_id, limit)
        
        # Get user's course enrollments
        enrolled_courses = self.db.query(Enrollment.course_id).filter(
            Enrollment.user_id == user_id
        ).all()
        course_ids = [c[0] for c in enrolled_courses]
        
        # Get videos from user's courses first
        course_videos = []
        if course_ids:
            course_videos = self.db.query(Video).filter(
                Video.course_id.in_(course_ids),
                Video.is_published
            ).order_by(desc(Video.created_at)).limit(limit // 2).all()
        
        # Get collaborative filtering recommendations
        cf_videos = await self._collaborative_filtering(user_id, limit // 2)
        
        # Combine and deduplicate
        seen_ids = set()
        recommendations = []
        
        for video in course_videos + cf_videos:
            if video.id not in seen_ids:
                recommendations.append(video)
                seen_ids.add(video.id)
                if len(recommendations) >= limit:
                    break
        
        return recommendations
    
    async def _get_cold_start_recommendations(self, user_id: int, limit: int) -> List[Video]:
        """Get recommendations for new users"""
        
        # Get user's enrolled courses
        enrolled_courses = self.db.query(Enrollment.course_id).filter(
            Enrollment.user_id == user_id
        ).all()
        course_ids = [c[0] for c in enrolled_courses]
        
        if course_ids:
            # Recommend recent videos from enrolled courses
            videos = self.db.query(Video).filter(
                Video.course_id.in_(course_ids),
                Video.is_published
            ).order_by(desc(Video.created_at)).limit(limit).all()
        else:
            # Recommend trending videos
            videos = await self.get_trending_videos(limit)
        
        return videos
    
    async def _collaborative_filtering(self, user_id: int, limit: int) -> List[Video]:
        """Simple collaborative filtering based on user interactions"""
        
        # Get user's liked and viewed videos
        user_interactions = self.db.query(UserVideoInteraction).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.interaction_type.in_(['like', 'view'])
        ).all()
        
        if not user_interactions:
            return []
        
        user_video_ids = [i.video_id for i in user_interactions]
        
        # Find users who interacted with same videos
        similar_users = self.db.query(
            UserVideoInteraction.user_id,
            func.count(UserVideoInteraction.video_id).label('common_count')
        ).filter(
            UserVideoInteraction.video_id.in_(user_video_ids),
            UserVideoInteraction.user_id != user_id
        ).group_by(
            UserVideoInteraction.user_id
        ).order_by(
            desc('common_count')
        ).limit(10).all()
        
        if not similar_users:
            return []
        
        similar_user_ids = [u[0] for u in similar_users]
        
        # Get videos liked by similar users that current user hasn't seen
        recommended_videos = self.db.query(Video).join(
            UserVideoInteraction,
            UserVideoInteraction.video_id == Video.id
        ).filter(
            UserVideoInteraction.user_id.in_(similar_user_ids),
            UserVideoInteraction.interaction_type == 'like',
            Video.id.notin_(user_video_ids),
            Video.is_published
        ).group_by(
            Video.id
        ).order_by(
            func.count(UserVideoInteraction.video_id).desc()
        ).limit(limit).all()
        
        return recommended_videos
    
    async def get_trending_videos(self, limit: int = 20, days: int = 7) -> List[Video]:
        """Get trending videos based on recent engagement"""
        
        # Calculate trending score for videos in last N days
        days_ago = datetime.utcnow() - timedelta(days=days)
        
        # Get videos with engagement metrics
        trending_videos = self.db.query(
            Video,
            (
                Video.view_count * 0.3 +
                Video.like_count * 0.5 +
                Video.comment_count * 0.2
            ).label('trending_score')
        ).filter(
            Video.created_at >= days_ago,
            Video.is_published
        ).order_by(
            desc('trending_score')
        ).limit(limit).all()
        
        return [video for video, _ in trending_videos]
    
    async def get_similar_videos(self, video_id: int, limit: int = 10) -> List[Video]:
        """
        Get videos similar to given video.
        FIXED: Removed .overlap() method which doesn't exist in SQLAlchemy
        """
        
        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return []
        
        # Start with videos from same course (best match)
        similar_videos = []
        
        if video.course_id:
            # Videos from same course (excluding current video)
            course_videos = self.db.query(Video).filter(
                Video.course_id == video.course_id,
                Video.id != video_id,
                Video.is_published
            ).order_by(
                desc(Video.view_count)
            ).limit(limit).all()
            
            similar_videos.extend(course_videos)
        
        # If we need more videos, find videos with similar tags
        if len(similar_videos) < limit and video.tags and len(video.tags) > 0:
            # Get videos that share at least one tag
            # Since tags is JSON field, we need to search differently
            
            # Create a list of tag conditions using JSON operations
            tag_conditions = []
            for tag in video.tags[:5]:  # Limit to first 5 tags
                # For PostgreSQL with JSONB
                if self.db.bind.dialect.name == 'postgresql':
                    tag_conditions.append(Video.tags.contains([tag]))
                else:
                    # For SQLite or other databases, use simple LIKE search
                    tag_conditions.append(Video.tags.cast(str).ilike(f'%{tag}%'))
            
            if tag_conditions:
                tag_matched_videos = self.db.query(Video).filter(
                    Video.id != video_id,
                    Video.is_published,
                    or_(*tag_conditions)
                ).order_by(
                    desc(Video.view_count)
                ).limit(limit - len(similar_videos)).all()
                
                # Add videos not already in similar_videos
                existing_ids = {v.id for v in similar_videos}
                for v in tag_matched_videos:
                    if v.id not in existing_ids:
                        similar_videos.append(v)
        
        # If still not enough, add trending videos as fallback
        if len(similar_videos) < limit:
            trending = await self.get_trending_videos(limit - len(similar_videos))
            existing_ids = {v.id for v in similar_videos}
            for video in trending:
                if video.id not in existing_ids and video.id != video_id:
                    similar_videos.append(video)
                    if len(similar_videos) >= limit:
                        break
        
        return similar_videos[:limit]
    
    async def get_course_recommendations(self, user_id: int, limit: int = 10) -> List[Course]:
        """Get course recommendations for user"""
        
        # Get user's enrolled courses
        enrolled_courses = self.db.query(Enrollment.course_id).filter(
            Enrollment.user_id == user_id
        ).all()
        enrolled_ids = [c[0] for c in enrolled_courses]
        
        # Get user's department
        user = self.db.query(User).filter(User.id == user_id).first()
        
        # Recommend courses from same department that user isn't enrolled in
        recommended_courses = self.db.query(Course).filter(
            Course.is_active,
            Course.id.notin_(enrolled_ids)
        )
        
        if user and user.department:
            recommended_courses = recommended_courses.filter(
                Course.department == user.department
            )
        
        recommended_courses = recommended_courses.order_by(
            desc(Course.enrollment_count)
        ).limit(limit).all()
        
        return recommended_courses
    
    async def get_user_recommendations(self, user_id: int, limit: int = 10) -> List[Video]:
        """Get hybrid recommendations combining multiple strategies"""
        
        # Get personalized feed
        personalized = await self.get_personalized_feed(user_id, limit // 2)
        
        # Get trending videos
        trending = await self.get_trending_videos(limit // 3)
        
        # Get videos from user's department
        user = self.db.query(User).filter(User.id == user_id).first()
        department_videos = []
        
        if user and user.department:
            department_videos = self.db.query(Video).join(
                Course, Video.course_id == Course.id
            ).filter(
                Course.department == user.department,
                Video.is_published,
                Video.id.notin_([v.id for v in personalized])
            ).order_by(
                desc(Video.view_count)
            ).limit(limit // 3).all()
        
        # Combine and deduplicate
        seen_ids = set()
        combined = []
        
        for video in personalized + trending + department_videos:
            if video.id not in seen_ids:
                combined.append(video)
                seen_ids.add(video.id)
                if len(combined) >= limit:
                    break
        
        return combined
    
    async def get_fresh_videos(self, hours: int = 24, limit: int = 20) -> List[Video]:
        """Get recently uploaded videos (fresh content)"""
        
        hours_ago = datetime.utcnow() - timedelta(hours=hours)
        
        fresh_videos = self.db.query(Video).filter(
            Video.created_at >= hours_ago,
            Video.is_published
        ).order_by(
            desc(Video.created_at)
        ).limit(limit).all()
        
        return fresh_videos
    
    async def get_user_watch_history(self, user_id: int, limit: int = 50) -> List[dict]:
        """Get user's watch history with video details"""
        
        history = self.db.query(
            UserVideoInteraction,
            Video.title,
            Video.thumbnail_url,
            Video.duration,
            Course.title.label('course_title')
        ).join(
            Video, UserVideoInteraction.video_id == Video.id
        ).outerjoin(
            Course, Video.course_id == Course.id
        ).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.interaction_type == 'view'
        ).order_by(
            desc(UserVideoInteraction.created_at)
        ).limit(limit).all()
        
        return [
            {
                "video_id": interaction.video_id,
                "video_title": video_title,
                "thumbnail_url": thumbnail_url,
                "duration": duration,
                "watch_percentage": interaction.watch_percentage,
                "watch_duration": interaction.watch_duration,
                "watched_at": interaction.created_at,
                "course_title": course_title
            }
            for interaction, video_title, thumbnail_url, duration, course_title in history
        ]
    
    async def get_popular_in_department(self, department: str, limit: int = 10) -> List[Video]:
        """Get popular videos in a specific department"""
        
        popular_videos = self.db.query(Video).join(
            Course, Video.course_id == Course.id
        ).filter(
            Course.department == department,
            Video.is_published
        ).order_by(
            desc(Video.view_count),
            desc(Video.like_count)
        ).limit(limit).all()
        
        return popular_videos