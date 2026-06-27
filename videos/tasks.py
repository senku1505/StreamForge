# videos/tasks.py
import subprocess
import os
from celery import shared_task
from django.conf import settings
from .models import Video

@shared_task
def process_video(video_id):
    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return "Video not found"

    if video.status != 'pending':
        return "Already processed"

    video.status = 'processing'
    video.save()

    input_path = video.original_file.path
    base_name = os.path.basename(input_path).split('.')[0]
    
    # Define output paths
    out_720_rel = f'processed/720p/{base_name}_720.mp4'
    out_480_rel = f'processed/480p/{base_name}_480.mp4'
    thumb_rel = f'thumbnails/{base_name}.jpg'
    
    out_720_abs = os.path.join(settings.MEDIA_ROOT, out_720_rel)
    out_480_abs = os.path.join(settings.MEDIA_ROOT, out_480_rel)
    thumb_abs = os.path.join(settings.MEDIA_ROOT, thumb_rel)

    # Ensure directories exist
    os.makedirs(os.path.dirname(out_720_abs), exist_ok=True)
    os.makedirs(os.path.dirname(out_480_abs), exist_ok=True)
    os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)

    try:
        # Generate 720p
        subprocess.run(['ffmpeg', '-y', '-i', input_path, '-vf', 'scale=-2:720', '-c:v', 'libx264', '-crf', '28', out_720_abs], check=True)
        # Generate 480p
        subprocess.run(['ffmpeg', '-y', '-i', input_path, '-vf', 'scale=-2:480', '-c:v', 'libx264', '-crf', '28', out_480_abs], check=True)
        # Generate Thumbnail (grab frame at 1 second)
        subprocess.run(['ffmpeg', '-y', '-i', input_path, '-ss', '00:00:01.000', '-vframes', '1', thumb_abs], check=True)

        # Update DB
        video.video_720.name = out_720_rel
        video.video_480.name = out_480_rel
        video.thumbnail.name = thumb_rel
        video.status = 'done'
        video.save()
        return "Success"
        
    except subprocess.CalledProcessError as e:
        video.status = 'failed'
        video.save()
        print(f"FFmpeg failed: {e}")
        return "Failed"