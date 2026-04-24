import os
import subprocess

# Path to your uploaded video
video_path = r"C:\Users\hp\Desktop\Projects\Media Learning Hub\mlh-backend\uploads\videos\2\ffb3a04a-5029-4951-b534-9d6e59e6496a.mp4"

# Check if video exists
if os.path.exists(video_path):
    print(f"✅ Video found: {video_path}")
    print(f"File size: {os.path.getsize(video_path)} bytes")
    
    # Test ffmpeg command
    thumbnail_path = "test_thumbnail.jpg"
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-ss', '00:00:01',
        '-vframes', '1',
        '-vf', 'scale=640:360',
        '-y',
        thumbnail_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Return code: {result.returncode}")
    print(f"Output: {result.stdout}")
    print(f"Error: {result.stderr}")
    
    if os.path.exists(thumbnail_path):
        print(f"✅ Thumbnail created: {thumbnail_path}")
        print(f"Thumbnail size: {os.path.getsize(thumbnail_path)} bytes")
    else:
        print("❌ Thumbnail not created")
else:
    print(f"❌ Video not found: {video_path}")