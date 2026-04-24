import os
import subprocess
import ffmpeg
from PIL import Image
from typing import Dict, List
import hashlib
from app.core.config import settings

class VideoProcessor:
    """Video processing utilities for transcoding, thumbnail generation, and metadata extraction"""
    
    def __init__(self):
        self.supported_formats = settings.ALLOWED_VIDEO_EXTENSIONS
        
    async def process_video(self, input_path: str, output_path: str, video_id: int) -> Dict:
        """Main video processing pipeline"""
        try:
            # Extract metadata
            metadata = await self.extract_metadata(input_path)
            
            # Generate thumbnail
            thumbnail_path = await self.generate_thumbnail(input_path, video_id)
            
            # Optimize video for streaming
            optimized_path = await self.optimize_for_streaming(input_path, output_path)
            
            # Generate multiple quality versions (optional)
            qualities = await self.generate_quality_variants(optimized_path, video_id)
            
            return {
                'metadata': metadata,
                'thumbnail': thumbnail_path,
                'optimized_video': optimized_path,
                'qualities': qualities,
                'duration': metadata.get('duration', 0),
                'file_size': os.path.getsize(optimized_path),
                'resolution': metadata.get('resolution', 'unknown')
            }
        except Exception as e:
            print(f"Video processing error: {e}")
            raise
    
    async def extract_metadata(self, video_path: str) -> Dict:
        """Extract video metadata using ffprobe"""
        try:
            probe = ffmpeg.probe(video_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
            
            metadata = {
                'duration': float(probe['format'].get('duration', 0)),
                'size': int(probe['format'].get('size', 0)),
                'bit_rate': int(probe['format'].get('bit_rate', 0)),
                'format': probe['format'].get('format_name', 'unknown'),
            }
            
            if video_stream:
                metadata.update({
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'resolution': f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}",
                    'video_codec': video_stream.get('codec_name', 'unknown'),
                    'frame_rate': eval(video_stream.get('avg_frame_rate', '0/1')) if video_stream.get('avg_frame_rate') else 0,
                })
            
            if audio_stream:
                metadata.update({
                    'audio_codec': audio_stream.get('codec_name', 'unknown'),
                    'audio_channels': audio_stream.get('channels', 0),
                    'sample_rate': int(audio_stream.get('sample_rate', 0)),
                })
            
            return metadata
        except Exception as e:
            print(f"Metadata extraction error: {e}")
            return {}
    
    async def generate_thumbnail(self, video_path: str, video_id: int, timestamp: float = 5.0) -> str:
        """Generate thumbnail from video at specified timestamp"""
        try:
            thumbnail_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "thumbnails", str(video_id))
            os.makedirs(thumbnail_dir, exist_ok=True)
            
            thumbnail_path = os.path.join(thumbnail_dir, "thumbnail.jpg")
            
            # Use ffmpeg to extract frame
            (
                ffmpeg
                .input(video_path, ss=timestamp)
                .output(thumbnail_path, vframes=1, format='image2', vcodec='mjpeg')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            
            # Resize thumbnail
            with Image.open(thumbnail_path) as img:
                # Resize to standard thumbnail size (720x480)
                img.thumbnail((720, 480), Image.Resampling.LANCZOS)
                img.save(thumbnail_path, 'JPEG', quality=85)
            
            return f"/uploads/thumbnails/{video_id}/thumbnail.jpg"
        except Exception as e:
            print(f"Thumbnail generation error: {e}")
            return None
    
    async def optimize_for_streaming(self, input_path: str, output_path: str) -> str:
        """Optimize video for web streaming with H.264 encoding"""
        try:
            output_dir = os.path.dirname(output_path)
            os.makedirs(output_dir, exist_ok=True)
            
            # Optimize with H.264 encoding and faststart for streaming
            (
                ffmpeg
                .input(input_path)
                .output(
                    output_path,
                    vcodec='libx264',
                    acodec='aac',
                    preset='medium',
                    crf=23,
                    movflags='+faststart',
                    **{'b:a': '128k'}
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            
            return output_path
        except Exception as e:
            print(f"Video optimization error: {e}")
            # Return original if optimization fails
            return input_path
    
    async def generate_quality_variants(self, video_path: str, video_id: int) -> Dict[str, str]:
        """Generate different quality versions for adaptive streaming"""
        qualities = {}
        quality_settings = {
            'low': {'width': 426, 'height': 240, 'bitrate': '400k'},
            'medium': {'width': 854, 'height': 480, 'bitrate': '1000k'},
            'high': {'width': 1280, 'height': 720, 'bitrate': '2500k'},
        }
        
        for quality, settings in quality_settings.items():
            try:
                quality_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "videos", str(video_id), quality)
                os.makedirs(quality_dir, exist_ok=True)
                
                quality_path = os.path.join(quality_dir, f"video_{quality}.mp4")
                
                (
                    ffmpeg
                    .input(video_path)
                    .output(
                        quality_path,
                    vcodec='libx264',
                    acodec='aac',
                    **{'s': f"{settings['width']}x{settings['height']}"},
                    **{'b:v': settings['bitrate']},
                    **{'b:a': '96k'}
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                
                qualities[quality] = f"/uploads/videos/{video_id}/{quality}/video_{quality}.mp4"
            except Exception as e:
                print(f"Quality variant generation error for {quality}: {e}")
        
        return qualities
    
    async def get_video_hash(self, video_path: str) -> str:
        """Generate SHA-256 hash of video file for deduplication"""
        sha256_hash = hashlib.sha256()
        with open(video_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    async def detect_scene_changes(self, video_path: str) -> List[float]:
        """Detect scene changes in video for chapter markers"""
        try:
            # Use ffmpeg scene detection
            cmd = [
                'ffmpeg', '-i', video_path,
                '-vf', 'select=gt(scene\\,0.4)',
                '-vsync', 'vfr',
                '-f', 'null', '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Parse timestamps from output
            timestamps = []
            import re
            pattern = r'pts_time:(\d+\.?\d*)'
            matches = re.findall(pattern, result.stderr)
            
            for match in matches:
                timestamps.append(float(match))
            
            return timestamps
        except Exception as e:
            print(f"Scene detection error: {e}")
            return []
    
    async def validate_video_integrity(self, video_path: str) -> bool:
        """Validate video file integrity"""
        try:
            # Check if file exists and has content
            if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
                return False
            
            # Try to probe video
            probe = ffmpeg.probe(video_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            return video_stream is not None
        except Exception:
            return False
    
    async def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds"""
        metadata = await self.extract_metadata(video_path)
        return metadata.get('duration', 0)
    
    async def create_hls_stream(self, video_path: str, output_dir: str) -> Dict[str, str]:
        """Create HLS streaming playlist with multiple qualities"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate master playlist
            master_playlist = os.path.join(output_dir, "master.m3u8")
            variants = []
            
            quality_settings = [
                {'name': 'low', 'width': 426, 'height': 240, 'bitrate': '400k'},
                {'name': 'medium', 'width': 854, 'height': 480, 'bitrate': '1000k'},
                {'name': 'high', 'width': 1280, 'height': 720, 'bitrate': '2500k'},
            ]
            
            for i, settings in enumerate(quality_settings):
                variant_dir = os.path.join(output_dir, settings['name'])
                os.makedirs(variant_dir, exist_ok=True)
                
                playlist_path = os.path.join(variant_dir, "playlist.m3u8")
                
                # Generate HLS segments
                (
                    ffmpeg
                    .input(video_path)
                    .output(
                        playlist_path,
                        **{
                            'c:v': 'libx264',
                            'c:a': 'aac',
                            'b:v': settings['bitrate'],
                            'b:a': '96k',
                            's': f"{settings['width']}x{settings['height']}",
                            'hls_time': 10,
                            'hls_list_size': 0,
                            'hls_segment_filename': os.path.join(variant_dir, "segment_%03d.ts"),
                            'hls_playlist_type': 'vod'
                        }
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                
                variants.append({
                    'bandwidth': int(settings['bitrate'].replace('k', '000')),
                    'resolution': f"{settings['width']}x{settings['height']}",
                    'url': f"{settings['name']}/playlist.m3u8"
                })
            
            # Generate master playlist
            with open(master_playlist, 'w') as f:
                f.write("#EXTM3U\n")
                f.write("#EXT-X-VERSION:3\n")
                for variant in variants:
                    f.write(f"#EXT-X-STREAM-INF:BANDWIDTH={variant['bandwidth']},RESOLUTION={variant['resolution']}\n")
                    f.write(f"{variant['url']}\n")
            
            return {
                'master_playlist': f"/uploads/hls/{os.path.basename(output_dir)}/master.m3u8",
                'variants': variants
            }
        except Exception as e:
            print(f"HLS creation error: {e}")
            return {}