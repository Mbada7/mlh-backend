"""
Educational Content Detection Service
======================================
Analyses uploaded video files by:
  1. Extracting frames every N seconds using OpenCV
  2. Extracting audio features (MFCCs, spectral centroid) using librosa
  3. Running both through a trained classifier (sklearn or PyTorch)
  4. Returning a confidence score + EDUCATIONAL / REJECTED decision

The service degrades gracefully:
  - If the trained model file is not found it falls back to heuristic rules
  - If OpenCV is not available it skips frame analysis
  - If librosa is not available it skips audio analysis
"""

import os
import logging
import tempfile
import shutil
from typing import Tuple, Dict, Any, List
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ── Optional heavy imports ────────────────────────────────────────────────────
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) not installed — frame analysis disabled")

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    logger.warning("librosa not installed — audio analysis disabled")

try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent   # mlh-backend/
MODEL_DIR = BASE_DIR / "ml_models"
SKLEARN_MODEL_PATH = MODEL_DIR / "educational_classifier.pkl"
TORCH_MODEL_PATH   = MODEL_DIR / "educational_model.pt"
SCALER_PATH        = MODEL_DIR / "feature_scaler.pkl"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── Thresholds ────────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.55   # >= this → EDUCATIONAL
FRAME_SAMPLE_INTERVAL = 3     # extract 1 frame every N seconds
MAX_FRAMES = 30               # cap total frames to keep it fast
AUDIO_DURATION_CAP = 120      # analyse first 2 minutes of audio only


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_video_frames(video_path: str) -> List[np.ndarray]:
    """
    Sample frames from the video at regular intervals.
    Returns a list of BGR numpy arrays (or empty list if cv2 unavailable).
    """
    if not CV2_AVAILABLE:
        return []

    frames = []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video: {video_path}")
        return frames

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    interval = int(fps * FRAME_SAMPLE_INTERVAL)
    if interval < 1:
        interval = 1

    frame_idx = 0
    while frame_idx < total_frames and len(frames) < MAX_FRAMES:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
        frame_idx += interval

    cap.release()
    logger.info(f"Extracted {len(frames)} frames from {video_path}")
    return frames


def extract_frame_features(frames: List[np.ndarray]) -> np.ndarray:
    """
    Convert raw frames into numerical features.

    Features per frame:
      - Mean brightness (1)
      - Brightness std (1)
      - Mean saturation (1)
      - Edge density via Canny (1)  ← whiteboards/slides have lots of edges
      - White pixel ratio (1)       ← slides / whiteboards tend to be mostly white
      - Text-like region density (1) ← regions with high horizontal edge concentration

    Returns shape (n_features,) averaged across all frames.
    """
    if not CV2_AVAILABLE or len(frames) == 0:
        return np.zeros(6)

    per_frame = []
    for frame in frames:
        try:
            # Resize to speed up processing
            small = cv2.resize(frame, (224, 224))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv   = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

            brightness     = float(gray.mean())
            brightness_std = float(gray.std())
            saturation     = float(hsv[:, :, 1].mean())

            # Edge density (whiteboards and slides are edge-rich)
            edges       = cv2.Canny(gray, 50, 150)
            edge_density = float(edges.mean()) / 255.0

            # White-pixel ratio (slides tend to have lots of white background)
            white_mask  = (gray > 220).astype(np.float32)
            white_ratio = float(white_mask.mean())

            # Simple text-region proxy: variance of horizontal gradients
            sobelx      = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            text_density = float(np.abs(sobelx).mean()) / 255.0

            per_frame.append([brightness, brightness_std, saturation,
                               edge_density, white_ratio, text_density])
        except Exception as e:
            logger.debug(f"Frame feature error: {e}")

    if not per_frame:
        return np.zeros(6)
    return np.mean(per_frame, axis=0)


def extract_audio_features(video_path: str) -> np.ndarray:
    """
    Extract audio features from the video.

    Features:
      - 13 MFCCs (mean + std = 26)  ← voice characteristics, speech patterns
      - Spectral centroid mean/std (2) ← speech sits in a certain frequency band
      - Zero crossing rate mean (1)    ← higher for speech vs music
      - RMS energy mean/std (2)        ← lecture has moderate consistent energy
      - Spectral rolloff mean (1)

    Returns shape (32,) or zeros if librosa unavailable.
    """
    if not LIBROSA_AVAILABLE:
        return np.zeros(32)

    try:
        y, sr = librosa.load(video_path, sr=22050, duration=AUDIO_DURATION_CAP, mono=True)

        if len(y) < sr:   # less than 1 second of audio
            return np.zeros(32)

        mfccs           = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        spectral_cent   = librosa.feature.spectral_centroid(y=y, sr=sr)
        zcr             = librosa.feature.zero_crossing_rate(y)
        rms             = librosa.feature.rms(y=y)
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)

        features = np.concatenate([
            mfccs.mean(axis=1),         # 13
            mfccs.std(axis=1),          # 13
            spectral_cent.mean(axis=1), # 1
            spectral_cent.std(axis=1),  # 1
            zcr.mean(axis=1),           # 1
            rms.mean(axis=1),           # 1
            rms.std(axis=1),            # 1
            spectral_rolloff.mean(axis=1),  # 1
        ])
        return features.astype(np.float32)

    except Exception as e:
        logger.error(f"Audio feature extraction failed: {e}")
        return np.zeros(32)


def build_feature_vector(video_path: str) -> np.ndarray:
    """Combine frame + audio features into one vector (38 features)."""
    frame_feats = np.zeros(6)
    audio_feats = np.zeros(32)

    if CV2_AVAILABLE:
        frames = extract_video_frames(video_path)
        frame_feats = extract_frame_features(frames)

    if LIBROSA_AVAILABLE:
        audio_feats = extract_audio_features(video_path)

    combined = np.concatenate([frame_feats, audio_feats]).astype(np.float32)
    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL LOADING
# ═══════════════════════════════════════════════════════════════════════════════

_sklearn_model = None
_scaler        = None
_torch_model   = None


def load_sklearn_model():
    global _sklearn_model, _scaler
    if _sklearn_model is not None:
        return _sklearn_model, _scaler
    if JOBLIB_AVAILABLE and SKLEARN_MODEL_PATH.exists():
        try:
            _sklearn_model = joblib.load(SKLEARN_MODEL_PATH)
            if SCALER_PATH.exists():
                _scaler = joblib.load(SCALER_PATH)
            logger.info(f"Loaded sklearn model from {SKLEARN_MODEL_PATH}")
            return _sklearn_model, _scaler
        except Exception as e:
            logger.error(f"Failed to load sklearn model: {e}")
    return None, None


class SimpleMLP(torch.nn.Module if TORCH_AVAILABLE else object):
    """Small MLP matching the architecture from educational-content-detection."""
    def __init__(self, input_dim: int = 38, hidden: int = 64):
        if TORCH_AVAILABLE:
            super().__init__()
            self.net = torch.nn.Sequential(
                torch.nn.Linear(input_dim, hidden),
                torch.nn.ReLU(),
                torch.nn.Dropout(0.3),
                torch.nn.Linear(hidden, 32),
                torch.nn.ReLU(),
                torch.nn.Linear(32, 1),
                torch.nn.Sigmoid(),
            )

    def forward(self, x):
        return self.net(x)


def load_torch_model():
    global _torch_model
    if _torch_model is not None:
        return _torch_model
    if TORCH_AVAILABLE and TORCH_MODEL_PATH.exists():
        try:
            model = SimpleMLP()
            model.load_state_dict(torch.load(TORCH_MODEL_PATH, map_location="cpu"))
            model.eval()
            _torch_model = model
            logger.info(f"Loaded PyTorch model from {TORCH_MODEL_PATH}")
            return _torch_model
        except Exception as e:
            logger.error(f"Failed to load PyTorch model: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# HEURISTIC FALLBACK (used when no trained model exists yet)
# ═══════════════════════════════════════════════════════════════════════════════

def heuristic_predict(features: np.ndarray) -> Tuple[float, str]:
    """
    Rule-based fallback when no model is trained yet.
    Uses visual and audio cues that strongly suggest lecture/educational content.

    Frame features [0..5]:
      0 = brightness mean
      1 = brightness std
      2 = saturation mean
      3 = edge density
      4 = white ratio
      5 = text density

    Audio features [6..37]:
      6..18  = MFCC means
      19..31 = MFCC stds
      32 = spectral centroid mean
      33 = spectral centroid std
      34 = ZCR mean
      35 = RMS mean
      36 = RMS std
      37 = spectral rolloff mean
    """
    score = 0.5   # start neutral

    # ── Visual cues ────────────────────────────────────────────────────────────
    if len(features) >= 6:
        brightness   = features[0]
        saturation   = features[2]
        edge_density = features[3]
        white_ratio  = features[4]
        text_density = features[5]

        # Lecture slides / whiteboards: bright, low saturation, lots of edges
        if brightness > 160:       score += 0.08
        if saturation < 40:        score += 0.06   # desaturated = slides/whiteboard
        if edge_density > 0.15:    score += 0.07   # edge-rich = text on slides
        if white_ratio > 0.4:      score += 0.08   # lots of white = slides/papers
        if text_density > 0.05:    score += 0.05

        # Penalty for entertainment-style video: very colourful & saturated
        if saturation > 100:       score -= 0.15
        if brightness < 60:        score -= 0.10   # dark scene = movie/game

    # ── Audio cues ─────────────────────────────────────────────────────────────
    if len(features) >= 38:
        zcr          = features[34]
        rms_mean     = features[35]
        rms_std      = features[36]
        spec_centroid = features[32]

        # Speech has moderate ZCR (not too high=noise, not too low=silence)
        if 0.03 < zcr < 0.15:    score += 0.08

        # Consistent moderate energy = lecture voice
        if 0.01 < rms_mean < 0.15:   score += 0.06
        if rms_std < 0.05:            score += 0.05   # consistent = calm lecture

        # Lecture speech typically 300–3000 Hz spectral centroid
        if 300 < spec_centroid < 3500:  score += 0.07

        # Heavy bass / sub-bass = music/entertainment
        if spec_centroid < 200:    score -= 0.15
        if spec_centroid > 6000:   score -= 0.10

    confidence = float(np.clip(score, 0.0, 1.0))
    label = "educational" if confidence >= CONFIDENCE_THRESHOLD else "not_educational"
    return confidence, label


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PREDICTION FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def predict_educational(video_path: str) -> Dict[str, Any]:
    """
    Main entry point.  Returns:
    {
        "is_educational": bool,
        "confidence": float (0–1),
        "label": "educational" | "not_educational",
        "method": "sklearn" | "pytorch" | "heuristic",
        "rejection_reason": str | None,
        "features_used": {"frames": bool, "audio": bool}
    }
    """
    if not os.path.exists(video_path):
        return {
            "is_educational": False, "confidence": 0.0,
            "label": "not_educational", "method": "error",
            "rejection_reason": "Video file not found for analysis",
            "features_used": {"frames": False, "audio": False},
        }

    logger.info(f"Analysing video: {video_path}")
    features = build_feature_vector(video_path)

    confidence = 0.5
    method     = "heuristic"

    # ── Try sklearn model first ────────────────────────────────────────────────
    sklearn_model, scaler = load_sklearn_model()
    if sklearn_model is not None:
        try:
            X = features.reshape(1, -1)
            if scaler is not None:
                X = scaler.transform(X)
            if hasattr(sklearn_model, "predict_proba"):
                proba = sklearn_model.predict_proba(X)[0]
                # class 1 = educational
                confidence = float(proba[1]) if len(proba) > 1 else float(proba[0])
            else:
                pred = sklearn_model.predict(X)[0]
                confidence = float(pred)
            method = "sklearn"
            logger.info(f"sklearn prediction: {confidence:.3f}")
        except Exception as e:
            logger.error(f"sklearn predict error: {e}")

    # ── Try PyTorch model ──────────────────────────────────────────────────────
    elif TORCH_AVAILABLE:
        torch_model = load_torch_model()
        if torch_model is not None:
            try:
                with torch.no_grad():
                    x = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
                    out = torch_model(x)
                    confidence = float(out.squeeze().item())
                method = "pytorch"
                logger.info(f"PyTorch prediction: {confidence:.3f}")
            except Exception as e:
                logger.error(f"PyTorch predict error: {e}")

    # ── Heuristic fallback ────────────────────────────────────────────────────
    if method == "heuristic":
        confidence, _ = heuristic_predict(features)
        logger.info(f"Heuristic prediction: {confidence:.3f}")

    is_educational = confidence >= CONFIDENCE_THRESHOLD
    label = "educational" if is_educational else "not_educational"

    rejection_reason = None
    if not is_educational:
        rejection_reason = (
            f"This video was classified as non-educational "
            f"(confidence score: {confidence:.0%}). "
            "Only academic lecture content, tutorials, or educational presentations "
            "are permitted on MSU LearningHub. "
            "Please ensure your video contains clear educational content such as "
            "lectures, demonstrations, or course-related material."
        )

    return {
        "is_educational": is_educational,
        "confidence": round(confidence, 4),
        "label": label,
        "method": method,
        "rejection_reason": rejection_reason,
        "features_used": {
            "frames": CV2_AVAILABLE,
            "audio":  LIBROSA_AVAILABLE,
        },
    }
