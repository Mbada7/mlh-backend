# MSU LearningHub — AI Library Installer
# Run this script from inside your mlh-backend folder with venv active
# Usage:  .\install_ai_libraries.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MSU LearningHub AI Library Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check we are in the right folder
if (-Not (Test-Path "main.py")) {
    Write-Host "ERROR: Run this script from inside the mlh-backend folder." -ForegroundColor Red
    Write-Host "       cd mlh-backend" -ForegroundColor Yellow
    exit 1
}

# ── Step 1: OpenCV (video frame reading) ──────────────────────────────────────
Write-Host "Installing OpenCV (video frame analysis)..." -ForegroundColor Yellow
pip install opencv-python-headless==4.9.0.80
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Trying alternative OpenCV package..." -ForegroundColor Yellow
    pip install opencv-python==4.9.0.80
}
Write-Host "OpenCV installed OK" -ForegroundColor Green

# ── Step 2: librosa (audio analysis) ─────────────────────────────────────────
Write-Host ""
Write-Host "Installing librosa (audio feature extraction)..." -ForegroundColor Yellow
pip install librosa==0.10.2.post1
Write-Host "librosa installed OK" -ForegroundColor Green

# ── Step 3: soundfile (audio file reading) ───────────────────────────────────
Write-Host ""
Write-Host "Installing soundfile..." -ForegroundColor Yellow
pip install soundfile==0.12.1
Write-Host "soundfile installed OK" -ForegroundColor Green

# ── Step 4: audioread (fallback audio decoder) ───────────────────────────────
Write-Host ""
Write-Host "Installing audioread..." -ForegroundColor Yellow
pip install audioread==3.0.1
Write-Host "audioread installed OK" -ForegroundColor Green

# ── Step 5: joblib (for saving/loading the trained model) ────────────────────
Write-Host ""
Write-Host "Installing joblib..." -ForegroundColor Yellow
pip install joblib==1.3.2
Write-Host "joblib installed OK" -ForegroundColor Green

# ── Step 6: PyTorch (optional — for neural network model) ────────────────────
Write-Host ""
Write-Host "Installing PyTorch (CPU version)..." -ForegroundColor Yellow
Write-Host "  This may take a few minutes..." -ForegroundColor Gray
pip install torch==2.2.2 torchvision==0.17.2 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyTorch CPU install failed — trying standard index..." -ForegroundColor Yellow
    pip install torch torchvision
}
Write-Host "PyTorch installed OK" -ForegroundColor Green

# ── Step 7: Verify all imports ────────────────────────────────────────────────
Write-Host ""
Write-Host "Verifying installations..." -ForegroundColor Yellow

$verifyScript = @"
import sys

results = {}

try:
    import cv2
    results['OpenCV'] = f'OK  (v{cv2.__version__})'
except ImportError as e:
    results['OpenCV'] = f'FAILED: {e}'

try:
    import librosa
    results['librosa'] = f'OK  (v{librosa.__version__})'
except ImportError as e:
    results['librosa'] = f'FAILED: {e}'

try:
    import soundfile
    results['soundfile'] = f'OK  (v{soundfile.__version__})'
except ImportError as e:
    results['soundfile'] = f'FAILED: {e}'

try:
    import joblib
    results['joblib'] = f'OK  (v{joblib.__version__})'
except ImportError as e:
    results['joblib'] = f'FAILED: {e}'

try:
    import torch
    results['PyTorch'] = f'OK  (v{torch.__version__})'
except ImportError as e:
    results['PyTorch'] = f'FAILED (optional): {e}'

print('')
for lib, status in results.items():
    icon = 'OK' if status.startswith('OK') else 'FAIL'
    print(f'  [{icon}]  {lib}: {status}')
print('')
"@

python -c $verifyScript

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Train the model (run once):" -ForegroundColor Yellow
Write-Host "       python train_model.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. Restart the backend:" -ForegroundColor Yellow
Write-Host "       uvicorn main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  3. Upload a test video in the app to see AI screening in action." -ForegroundColor Yellow
Write-Host ""
