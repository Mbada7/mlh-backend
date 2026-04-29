"""
train_model.py
==============
Run this script ONCE to train and save the educational content classifier.

Usage (from inside mlh-backend with venv active):
    python train_model.py

The script will:
  1. Look for training data in  ml_models/training_data/
         educational/   ← put educational videos here
         not_educational/ ← put non-educational videos here
  2. Extract frame + audio features from every video
  3. Train a RandomForest + SVM ensemble
  4. Save  ml_models/educational_classifier.pkl
          ml_models/feature_scaler.pkl
  5. Print accuracy and classification report

If you have the educational-content-detection-main dataset,
copy its video files into the folders above before running this.
"""

import os
import sys
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).resolve().parent
MODEL_DIR      = BASE_DIR / "ml_models"
TRAIN_DIR      = MODEL_DIR / "training_data"
EDU_DIR        = TRAIN_DIR / "educational"
NON_EDU_DIR    = TRAIN_DIR / "not_educational"
MODEL_OUT      = MODEL_DIR / "educational_classifier.pkl"
SCALER_OUT     = MODEL_DIR / "feature_scaler.pkl"

for d in [MODEL_DIR, EDU_DIR, NON_EDU_DIR]:
    d.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}


def check_dependencies():
    missing = []
    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")
    try:
        import librosa
    except ImportError:
        missing.append("librosa")
    try:
        import sklearn
    except ImportError:
        missing.append("scikit-learn")
    try:
        import joblib
    except ImportError:
        missing.append("joblib")

    if missing:
        print(f"\n❌  Missing packages: {', '.join(missing)}")
        print(f"    Run: pip install {' '.join(missing)}")
        sys.exit(1)

    print("✅  All dependencies present")


def collect_videos(folder: Path, label: int) -> list:
    """Return list of (video_path, label) tuples."""
    items = []
    if not folder.exists():
        logger.warning(f"Training folder not found: {folder}")
        return items
    for f in folder.iterdir():
        if f.suffix.lower() in VIDEO_EXTS:
            items.append((str(f), label))
    return items


def extract_features_for_dataset(items: list) -> tuple:
    """Extract features for all videos. Returns X, y arrays."""
    from app.services.content_detection import build_feature_vector

    X, y = [], []
    for video_path, label in items:
        logger.info(f"Processing {'EDU' if label == 1 else 'NON-EDU'}: {Path(video_path).name}")
        try:
            feats = build_feature_vector(video_path)
            X.append(feats)
            y.append(label)
        except Exception as e:
            logger.error(f"  Failed: {e}")

    if not X:
        return np.array([]), np.array([])

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32)


def train(X: np.ndarray, y: np.ndarray):
    """Train ensemble and save model + scaler."""
    import joblib
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier, GradientBoostingClassifier
    from sklearn.svm import SVC
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.metrics import classification_report, accuracy_score

    logger.info(f"Training on {len(X)} samples  (EDU={y.sum()}  NON={len(y)-y.sum()})")

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Ensemble: RandomForest + GradientBoosting + SVM
    rf  = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42, n_jobs=-1)
    gb  = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
    svm = SVC(kernel="rbf", probability=True, random_state=42, C=2.0)

    clf = VotingClassifier(
        estimators=[("rf", rf), ("gb", gb), ("svm", svm)],
        voting="soft",
        weights=[2, 1, 1],
    )

    # Cross-validation
    cv = StratifiedKFold(n_splits=min(5, len(np.unique(y))), shuffle=True, random_state=42)
    scores = cross_val_score(clf, X_scaled, y, cv=cv, scoring="f1")
    logger.info(f"Cross-val F1: {scores.mean():.3f} ± {scores.std():.3f}")

    # Fit on all data
    clf.fit(X_scaled, y)
    preds = clf.predict(X_scaled)

    print("\n" + "="*55)
    print("TRAINING COMPLETE")
    print("="*55)
    print(f"Training accuracy : {accuracy_score(y, preds):.2%}")
    print(f"Cross-val F1 mean : {scores.mean():.3f}")
    print("\nClassification Report:")
    print(classification_report(y, preds, target_names=["not_educational", "educational"]))

    # Save
    joblib.dump(clf,    MODEL_OUT)
    joblib.dump(scaler, SCALER_OUT)
    print(f"\n✅  Model  saved → {MODEL_OUT}")
    print(f"✅  Scaler saved → {SCALER_OUT}")
    return clf, scaler


def demo_predict(clf, scaler, X: np.ndarray, y: np.ndarray, items: list):
    """Quick sanity check on the first few samples."""
    print("\nSample predictions:")
    for i in range(min(5, len(X))):
        x_s = scaler.transform(X[i:i+1])
        proba = clf.predict_proba(x_s)[0]
        pred_label = "educational" if proba[1] >= 0.55 else "not_educational"
        true_label = "educational" if y[i] == 1 else "not_educational"
        match = "✓" if pred_label == true_label else "✗"
        print(f"  {match} {Path(items[i][0]).name[:40]:40s}  "
              f"conf={proba[1]:.2f}  pred={pred_label}  true={true_label}")


# ── Synthetic data generator ───────────────────────────────────────────────────
def generate_synthetic_data(n_edu: int = 80, n_nonedu: int = 80):
    """
    Generate synthetic training samples based on known feature patterns.
    Used when you do not have real video files yet, so you can still train
    a baseline model immediately.

    Frame features [0..5]:   brightness, brightness_std, saturation,
                              edge_density, white_ratio, text_density
    Audio features [6..37]:  MFCCs x13 mean, MFCCs x13 std,
                              spectral_centroid_mean, spectral_centroid_std,
                              zcr, rms_mean, rms_std, spectral_rolloff
    """
    rng = np.random.default_rng(42)

    def make_edu(n):
        rows = []
        for _ in range(n):
            brightness   = rng.uniform(150, 240)
            bright_std   = rng.uniform(20,  50)
            saturation   = rng.uniform(5,   40)
            edge_density = rng.uniform(0.12, 0.35)
            white_ratio  = rng.uniform(0.35, 0.70)
            text_density = rng.uniform(0.06, 0.20)

            mfcc_mean = rng.normal(-5, 30, 13)
            mfcc_std  = rng.uniform(5, 20, 13)
            spec_cent_m = rng.uniform(800, 3000)
            spec_cent_s = rng.uniform(50,  400)
            zcr           = rng.uniform(0.04, 0.12)
            rms_mean_val  = rng.uniform(0.02, 0.10)
            rms_std_val   = rng.uniform(0.005, 0.03)
            rolloff       = rng.uniform(1000, 3500)

            row = [brightness, bright_std, saturation, edge_density,
                   white_ratio, text_density,
                   *mfcc_mean, *mfcc_std,
                   spec_cent_m, spec_cent_s, zcr,
                   rms_mean_val, rms_std_val, rolloff]
            rows.append(row)
        return np.array(rows, dtype=np.float32)

    def make_nonedu(n):
        rows = []
        for _ in range(n):
            brightness   = rng.uniform(30,  160)
            bright_std   = rng.uniform(40,  90)
            saturation   = rng.uniform(60,  180)
            edge_density = rng.uniform(0.02, 0.12)
            white_ratio  = rng.uniform(0.02, 0.25)
            text_density = rng.uniform(0.00, 0.04)

            mfcc_mean = rng.normal(10, 50, 13)
            mfcc_std  = rng.uniform(20, 60, 13)
            spec_cent_m = rng.uniform(100, 500)
            spec_cent_s = rng.uniform(200, 800)
            zcr           = rng.uniform(0.15, 0.40)
            rms_mean_val  = rng.uniform(0.10, 0.30)
            rms_std_val   = rng.uniform(0.05, 0.15)
            rolloff       = rng.uniform(4000, 10000)

            row = [brightness, bright_std, saturation, edge_density,
                   white_ratio, text_density,
                   *mfcc_mean, *mfcc_std,
                   spec_cent_m, spec_cent_s, zcr,
                   rms_mean_val, rms_std_val, rolloff]
            rows.append(row)
        return np.array(rows, dtype=np.float32)

    X_edu    = make_edu(n_edu)
    X_nonedu = make_nonedu(n_nonedu)
    X = np.vstack([X_edu, X_nonedu])
    y = np.concatenate([np.ones(n_edu, dtype=np.int32),
                        np.zeros(n_nonedu, dtype=np.int32)])

    # Shuffle
    idx = rng.permutation(len(X))
    return X[idx], y[idx]


if __name__ == "__main__":
    check_dependencies()

    # Collect real video files
    edu_items    = collect_videos(EDU_DIR,     label=1)
    nonedu_items = collect_videos(NON_EDU_DIR, label=0)
    all_items    = edu_items + nonedu_items

    if len(all_items) >= 10:
        print(f"\nFound {len(edu_items)} educational  +  "
              f"{len(nonedu_items)} non-educational videos")
        print("Extracting features — this may take several minutes...\n")
        X, y = extract_features_for_dataset(all_items)
    else:
        print(f"\n⚠️  Not enough video files found "
              f"({len(edu_items)} edu, {len(nonedu_items)} non-edu).")
        print("   Using synthetic training data as baseline.")
        print("   Add real videos to ml_models/training_data/ and re-run for better accuracy.\n")
        X, y = generate_synthetic_data(n_edu=120, n_nonedu=120)
        all_items = []

    if len(X) == 0:
        print("❌  No features extracted. Cannot train. Exiting.")
        sys.exit(1)

    clf, scaler = train(X, y)

    if all_items:
        demo_predict(clf, scaler, X, y, all_items)

    print("\nNext steps:")
    print("  1. Restart the FastAPI backend — it will load the new model automatically")
    print("  2. Upload a test video via the app to verify classification")
    print("  3. For better accuracy, add more labelled videos to")
    print(f"     {EDU_DIR}")
    print(f"     {NON_EDU_DIR}")
    print("     and run this script again.\n")
