import numpy as np
from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler
from collections import defaultdict
from datetime import datetime, timedelta
from app.models.video import Video
from app.models.interaction import UserVideoInteraction
from app.models.recommendation import UserEmbedding, VideoEmbedding, RecommendationFeedback, ModelMetrics
from app.core.config import settings


class MLService:
    """Machine Learning service for recommendations and analytics"""

    def __init__(self, db: Session):
        self.db = db
        self.scaler = StandardScaler()

    async def generate_user_embeddings(self, user_id: int) -> np.ndarray:
        """Generate user embedding based on interaction history"""

        # FIX: Select the full Video ORM object so video.course_id and video.tags work correctly
        interactions = self.db.query(
            UserVideoInteraction,
            Video
        ).join(
            Video, UserVideoInteraction.video_id == Video.id
        ).filter(
            UserVideoInteraction.user_id == user_id
        ).all()

        if not interactions:
            # Return random embedding for new users
            return np.random.randn(settings.EMBEDDING_DIMENSION)

        # Initialize feature vector
        feature_vector = np.zeros(settings.EMBEDDING_DIMENSION)

        # 1. Content preference features (based on tags and courses)
        course_prefs = defaultdict(int)
        tag_prefs = defaultdict(int)

        # FIX: Unpack two values (interaction, video) — matches the corrected query above
        for interaction, video in interactions:
            if interaction.interaction_type == 'like':
                weight = 2.0
            elif interaction.interaction_type == 'view':
                weight = 1.0
            elif interaction.interaction_type == 'complete':
                weight = 1.5
            else:
                weight = 0.5

            # Weight by watch percentage
            weight *= (interaction.watch_percentage + 0.5)

            if video.course_id:
                course_prefs[video.course_id] += weight

            if video.tags:
                for tag in video.tags:
                    tag_prefs[tag] += weight

        # 2. Temporal features (recent interactions weighted higher)
        recent_weight = 1.0
        for interaction, video in interactions[-20:]:
            feature_vector[:50] += recent_weight * np.random.randn(50)
            recent_weight *= 0.9

        # 3. Combine features
        course_vals = list(course_prefs.values())[:50]
        tag_vals = list(tag_prefs.values())[:50]

        feature_vector[50:50 + len(course_vals)] = course_vals
        feature_vector[100:100 + len(tag_vals)] = tag_vals

        # Normalize
        norm = np.linalg.norm(feature_vector)
        if norm > 0:
            feature_vector = feature_vector / norm

        # Store in database
        embedding = self.db.query(UserEmbedding).filter(UserEmbedding.user_id == user_id).first()
        if embedding:
            embedding.embedding_vector = feature_vector.tolist()
            embedding.updated_at = datetime.utcnow()
        else:
            embedding = UserEmbedding(
                user_id=user_id,
                embedding_vector=feature_vector.tolist()
            )
            self.db.add(embedding)

        self.db.commit()
        return feature_vector

    async def generate_video_embeddings(self, video_id: int) -> np.ndarray:
        """Generate embedding for video based on metadata and interactions"""

        video = self.db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return np.random.randn(settings.EMBEDDING_DIMENSION)

        feature_vector = np.zeros(settings.EMBEDDING_DIMENSION)

        # 1. Metadata features
        feature_vector[0] = min(len(video.title or '') / 100, 1.0)
        feature_vector[1] = min(len(video.description or '') / 1000, 1.0)

        # 2. Engagement features
        total_interactions = self.db.query(func.count(UserVideoInteraction.id)).filter(
            UserVideoInteraction.video_id == video_id
        ).scalar() or 1

        engagement_score = (
            video.like_count * 2 + video.comment_count * 3 + video.share_count * 4
        ) / total_interactions
        feature_vector[2] = min(engagement_score, 1.0)

        # 3. Course embedding
        if video.course_id:
            feature_vector[3] = video.course_id / 1000

        # 4. Tag embedding (simple hash-based)
        if video.tags:
            for i, tag in enumerate(video.tags[:10]):
                tag_hash = hash(tag) % (settings.EMBEDDING_DIMENSION - 100)
                feature_vector[100 + tag_hash] += 1

        # Normalize
        norm = np.linalg.norm(feature_vector)
        if norm > 0:
            feature_vector = feature_vector / norm

        # Store in database
        embedding = self.db.query(VideoEmbedding).filter(VideoEmbedding.video_id == video_id).first()
        if embedding:
            embedding.embedding_vector = feature_vector.tolist()
            embedding.updated_at = datetime.utcnow()
        else:
            embedding = VideoEmbedding(
                video_id=video_id,
                embedding_vector=feature_vector.tolist()
            )
            self.db.add(embedding)

        self.db.commit()
        return feature_vector

    async def find_similar_users(self, user_id: int, limit: int = 10) -> List[Tuple[int, float]]:
        """Find users with similar preferences using cosine similarity"""

        target_embedding = self.db.query(UserEmbedding).filter(
            UserEmbedding.user_id == user_id
        ).first()

        if not target_embedding:
            return []

        target_vector = np.array(target_embedding.embedding_vector)

        other_embeddings = self.db.query(UserEmbedding).filter(
            UserEmbedding.user_id != user_id
        ).all()

        if not other_embeddings:
            return []

        similarities = []
        for emb in other_embeddings:
            other_vector = np.array(emb.embedding_vector)
            similarity = cosine_similarity([target_vector], [other_vector])[0][0]
            similarities.append((emb.user_id, float(similarity)))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]

    async def find_similar_videos(self, video_id: int, limit: int = 10) -> List[Tuple[int, float]]:
        """Find videos similar to given video using embeddings"""

        target_embedding = self.db.query(VideoEmbedding).filter(
            VideoEmbedding.video_id == video_id
        ).first()

        if not target_embedding:
            return []

        target_vector = np.array(target_embedding.embedding_vector)

        other_embeddings = self.db.query(VideoEmbedding).filter(
            VideoEmbedding.video_id != video_id
        ).all()

        if not other_embeddings:
            return []

        similarities = []
        for emb in other_embeddings:
            other_vector = np.array(emb.embedding_vector)
            similarity = cosine_similarity([target_vector], [other_vector])[0][0]
            similarities.append((emb.video_id, float(similarity)))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:limit]

    async def compute_engagement_score(self, user_id: int) -> float:
        """Compute user engagement score (0-100)"""

        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        stats = self.db.query(
            func.count(UserVideoInteraction.id).label('total_interactions'),
            func.sum(UserVideoInteraction.watch_duration).label('total_watch_time'),
            func.count(func.distinct(UserVideoInteraction.video_id)).label('unique_videos')
        ).filter(
            UserVideoInteraction.user_id == user_id,
            UserVideoInteraction.created_at >= thirty_days_ago
        ).first()

        if not stats.total_interactions:
            return 0.0

        interaction_score = min(stats.total_interactions / 100, 1.0) * 30
        watch_time_score = min((stats.total_watch_time or 0) / 36000, 1.0) * 35  # guard None
        diversity_score = min(stats.unique_videos / 50, 1.0) * 35

        total_score = interaction_score + watch_time_score + diversity_score
        return min(total_score, 100.0)

    async def update_recommendation_model(self):
        """Retrain or update recommendation models based on feedback"""

        week_ago = datetime.utcnow() - timedelta(days=7)

        feedback = self.db.query(RecommendationFeedback).filter(
            RecommendationFeedback.created_at >= week_ago
        ).all()

        if len(feedback) < 100:
            return {"status": "insufficient_data", "feedback_count": len(feedback)}

        precision = await self._calculate_precision_at_k(feedback, k=10)
        recall = await self._calculate_recall_at_k(feedback, k=10)
        ndcg = await self._calculate_ndcg(feedback, k=10)

        metrics_data = [
            ("collaborative_filtering", "precision@10", precision),
            ("collaborative_filtering", "recall@10", recall),
            ("collaborative_filtering", "ndcg@10", ndcg)
        ]

        for model_name, metric_name, value in metrics_data:
            metric = ModelMetrics(
                model_name=model_name,
                model_version="v1.0",
                metric_name=metric_name,
                metric_value=value,
                test_size=len(feedback)
            )
            self.db.add(metric)

        self.db.commit()

        return {
            "status": "model_updated",
            "metrics": {
                "precision@10": precision,
                "recall@10": recall,
                "ndcg@10": ndcg
            },
            "feedback_count": len(feedback)
        }

    async def _calculate_precision_at_k(self, feedback: List, k: int) -> float:
        """Calculate precision@k metric"""
        if not feedback:
            return 0.0

        relevant_count = sum(1 for f in feedback if f.clicked == 1 or f.liked == 1)
        return relevant_count / min(len(feedback), k)

    async def _calculate_recall_at_k(self, feedback: List, k: int) -> float:
        """Calculate recall@k metric"""
        if not feedback:
            return 0.0

        clicked = sum(1 for f in feedback if f.clicked == 1)
        if clicked == 0:
            return 0.0

        relevant_in_top_k = sum(1 for f in feedback[:k] if f.clicked == 1)
        return relevant_in_top_k / clicked

    async def _calculate_ndcg(self, feedback: List, k: int) -> float:
        """Calculate NDCG@k metric"""
        if not feedback:
            return 0.0

        dcg = 0.0
        for i, f in enumerate(feedback[:k]):
            relevance = 1 if f.clicked == 1 or f.liked == 1 else 0
            dcg += relevance / np.log2(i + 2)

        ideal_relevance = sorted(
            [1 if f.clicked == 1 else 0 for f in feedback], reverse=True
        )[:k]
        idcg = 0.0
        for i, rel in enumerate(ideal_relevance):
            idcg += rel / np.log2(i + 2)

        return dcg / idcg if idcg > 0 else 0.0
