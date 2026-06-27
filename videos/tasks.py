# videos/tasks.py
import subprocess
import os
import json
import math

from celery import shared_task
from django.conf import settings
from .models import Video


def _run(cmd):
    """Run a subprocess command, suppressing stdout, surfacing stderr on failure."""
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, stderr=result.stderr)


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
    media_root = settings.MEDIA_ROOT

    # ── Output directories ────────────────────────────────────────────
    hls_dir   = os.path.join(media_root, 'hls', str(video_id))
    dir_720   = os.path.join(hls_dir, '720p')
    dir_480   = os.path.join(hls_dir, '480p')
    thumb_dir = os.path.join(media_root, 'thumbnails')
    spr_dir   = os.path.join(media_root, 'sprites')

    for d in [dir_720, dir_480, thumb_dir, spr_dir]:
        os.makedirs(d, exist_ok=True)

    try:
        # ── 1. Duration via ffprobe ───────────────────────────────────
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', input_path],
            capture_output=True, text=True, check=True,
        )
        fmt_data = json.loads(probe.stdout).get('format', {})
        duration = float(fmt_data.get('duration', 0) or 0)
        video.duration = round(duration, 2)
        video.save()

        # ── 2. HLS 720p rendition ─────────────────────────────────────
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'scale=-2:720',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '128k',
            '-hls_time', '6',
            '-hls_playlist_type', 'vod',
            '-hls_segment_filename', os.path.join(dir_720, 'seg%03d.ts'),
            os.path.join(dir_720, 'stream.m3u8'),
        ])

        # ── 3. HLS 480p rendition ─────────────────────────────────────
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'scale=-2:480',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '96k',
            '-hls_time', '6',
            '-hls_playlist_type', 'vod',
            '-hls_segment_filename', os.path.join(dir_480, 'seg%03d.ts'),
            os.path.join(dir_480, 'stream.m3u8'),
        ])

        # ── 4. HLS master playlist ────────────────────────────────────
        master_path = os.path.join(hls_dir, 'master.m3u8')
        with open(master_path, 'w') as f:
            f.write(
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n\n"
                '#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,NAME="720p"\n'
                "720p/stream.m3u8\n"
                '#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=854x480,NAME="480p"\n'
                "480p/stream.m3u8\n"
            )

        # ── 5. Thumbnail (at 10% through video, minimum 1 s) ─────────
        thumb_at  = max(1.0, duration * 0.1)
        thumb_abs = os.path.join(thumb_dir, f'{video_id}.jpg')
        _run([
            'ffmpeg', '-y', '-ss', str(thumb_at), '-i', input_path,
            '-vframes', '1', '-vf', 'scale=1280:-2', '-q:v', '3',
            thumb_abs,
        ])

        # ── 6. Sprite sheet (1 frame / 5 s, 160×90 tiles, 10 cols) ──
        num_frames = max(1, math.ceil(duration / 5))
        cols       = min(10, num_frames)
        rows       = math.ceil(num_frames / cols)
        sprite_abs = os.path.join(spr_dir, f'{video_id}.jpg')
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', f'fps=1/5,scale=160:90,tile={cols}x{rows}',
            '-frames:v', '1', '-q:v', '4',
            sprite_abs,
        ])

        # ── 7. Persist paths and mark done ────────────────────────────
        video.hls_master.name   = f'hls/{video_id}/master.m3u8'
        video.thumbnail.name    = f'thumbnails/{video_id}.jpg'
        video.sprite_sheet.name = f'sprites/{video_id}.jpg'
        video.status = 'done'
        video.save()
        return "Success"

    except subprocess.CalledProcessError as e:
        video.status = 'failed'
        video.save()
        stderr_msg = e.stderr.decode(errors='replace') if e.stderr else str(e)
        print(f"[StreamForge] FFmpeg pipeline failed for video {video_id}:\n{stderr_msg}")
        return "Failed"

    except Exception as e:
        video.status = 'failed'
        video.save()
        print(f"[StreamForge] Unexpected error for video {video_id}: {e}")
        return "Failed"
