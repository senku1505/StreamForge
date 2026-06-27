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


def check_and_enforce_storage_limit():
    import os
    from django.conf import settings
    
    total_size = 0
    media_root = settings.MEDIA_ROOT
    if os.path.exists(media_root):
        for dirpath, dirnames, filenames in os.walk(media_root):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
                        
    LIMIT_5GB = 5 * 1024 * 1024 * 1024
    if total_size > LIMIT_5GB:
        oldest_videos = Video.objects.all().order_by('created_at')[:2]
        for video in oldest_videos:
            try:
                video.delete()
            except Exception as e:
                print(f"[StreamForge] Failed to delete old video {video.id} under storage quota: {e}")


@shared_task
def process_video(video_id):
    # Enforce 5GB storage limit check
    try:
        check_and_enforce_storage_limit()
    except Exception as e:
        print(f"[StreamForge] Storage limit check failed: {e}")

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
    dir_1080  = os.path.join(hls_dir, '1080p')
    dir_720   = os.path.join(hls_dir, '720p')
    thumb_dir = os.path.join(media_root, 'thumbnails')
    spr_dir   = os.path.join(media_root, 'sprites')
    gif_dir   = os.path.join(media_root, 'previews')

    for d in [dir_1080, dir_720, thumb_dir, spr_dir, gif_dir]:
        os.makedirs(d, exist_ok=True)

    try:
        # ── 1. Metadata via ffprobe ───────────────────────────────────
        video.status = 'analyzing'
        video.save()

        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', input_path],
            capture_output=True, text=True, check=True,
        )
        probe_data = json.loads(probe.stdout)
        fmt_data   = probe_data.get('format', {})
        streams    = probe_data.get('streams', [])
        
        # Find video stream
        video_stream = next((s for s in streams if s.get('codec_type') == 'video'), {})
        
        # Duration
        duration = float(fmt_data.get('duration', 0) or 0)
        video.duration = round(duration, 2)
        
        # Resolution
        width = video_stream.get('width')
        height = video_stream.get('height')
        if width and height:
            video.resolution = f"{width}x{height}"
            
        # Codec
        video.codec = video_stream.get('codec_name', '').upper()
        
        # FPS
        r_frame_rate = video_stream.get('r_frame_rate', '')
        if '/' in r_frame_rate:
            try:
                num, den = map(int, r_frame_rate.split('/'))
                if den > 0:
                    fps = num / den
                    video.fps = f"{round(fps, 2)} fps"
            except Exception:
                video.fps = "—"
        else:
            video.fps = f"{r_frame_rate} fps" if r_frame_rate else "—"
            
        # Bitrate
        bitrate_bps = float(fmt_data.get('bit_rate', 0) or video_stream.get('bit_rate', 0) or 0)
        if bitrate_bps > 0:
            video.bitrate = f"{round(bitrate_bps / 1000000, 2)} Mbps"
        else:
            video.bitrate = "—"
            
        video.save()

        # ── 2. HLS 1080p rendition ────────────────────────────────────
        video.status = 'transcoding_1080p'
        video.save()
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'scale=-2:1080',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '192k',
            '-hls_time', '6',
            '-hls_playlist_type', 'vod',
            '-hls_segment_filename', os.path.join(dir_1080, 'seg%03d.ts'),
            os.path.join(dir_1080, 'stream.m3u8'),
        ])

        # ── 3. HLS 720p rendition ─────────────────────────────────────
        video.status = 'transcoding_720p'
        video.save()
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

        # ── 4. HLS master playlist ────────────────────────────────────
        master_path = os.path.join(hls_dir, 'master.m3u8')
        with open(master_path, 'w') as f:
            f.write(
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n\n"
                '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,NAME="1080p"\n'
                "1080p/stream.m3u8\n"
                '#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720,NAME="720p"\n'
                "720p/stream.m3u8\n"
            )

        # ── 5. HLS GIF preview (3 seconds from 40% duration) ──────────
        video.status = 'generating_gif'
        video.save()
        gif_abs = os.path.join(gif_dir, f'{video_id}.gif')
        gif_start = max(0.0, duration * 0.4)
        _run([
            'ffmpeg', '-y', '-ss', str(gif_start), '-t', '3', '-i', input_path,
            '-vf', 'fps=10,scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2',
            gif_abs
        ])

        # ── 6. Assets (Thumbnail & Sprite Sheet) ──────────────────────
        video.status = 'generating_assets'
        video.save()
        
        # Thumbnail (at 10% through video, minimum 1 s)
        thumb_at  = max(1.0, duration * 0.1)
        thumb_abs = os.path.join(thumb_dir, f'{video_id}.jpg')
        _run([
            'ffmpeg', '-y', '-ss', str(thumb_at), '-i', input_path,
            '-vframes', '1', '-vf', 'scale=1280:-2', '-q:v', '3',
            thumb_abs,
        ])

        # Sprite sheet (1 frame / 5 s, 160×90 tiles, 10 cols)
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
        video.gif_preview.name  = f'previews/{video_id}.gif'
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
