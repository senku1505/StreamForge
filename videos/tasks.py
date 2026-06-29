import os
import subprocess
import json
import math
import traceback
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from .models import Video


def _run(cmd):
    """Run a subprocess command, raise on failure."""
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, stderr=result.stderr)


def check_and_enforce_storage_limit():
    """Keep total local storage under 5 GB."""
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

    limit = 5 * 1024 * 1024 * 1024  # 5 GB
    if total_size > limit:
        oldest = Video.objects.all().order_by('created_at')[:2]
        for video in oldest:
            try:
                video.delete()
            except Exception as e:
                print(f"[Quota] delete failed for {video.id}: {e}")


def _s3_upload(s3_path, data_bytes):
    """Upload bytes to S3/R2 at the given path."""
    if default_storage.exists(s3_path):
        default_storage.delete(s3_path)
    default_storage.save(s3_path, ContentFile(data_bytes))


@shared_task
def process_video(video_id):
    use_s3 = getattr(settings, 'USE_S3', False)
    if not use_s3:
        try:
            check_and_enforce_storage_limit()
        except Exception as e:
            print(f"[Quota] check failed: {e}")

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return "Video not found"

    if video.status != 'pending':
        return "Already processed"

    # ── temp workspace ───────────────────────────────────────────────────────
    if use_s3:
        tmp_dir_obj = tempfile.TemporaryDirectory()
        working_dir = tmp_dir_obj.name
        input_filename = os.path.basename(video.original_file.name)
        input_path = os.path.join(working_dir, input_filename)

        try:
            with default_storage.open(video.original_file.name, 'rb') as source:
                with open(input_path, 'wb') as dest:
                    for chunk in source.chunks():
                        dest.write(chunk)
        except Exception as e:
            tmp_dir_obj.cleanup()
            raise RuntimeError(f"Failed to download original file from S3: {e}")
    else:
        tmp_dir_obj = None
        working_dir = None
        input_path = video.original_file.path
        media_root = settings.MEDIA_ROOT

    hls_dir  = os.path.join(working_dir or (settings.MEDIA_ROOT), 'hls', str(video_id)) if not use_s3 else os.path.join(working_dir, 'hls')
    dir_1080 = os.path.join(hls_dir, '1080p')
    dir_720  = os.path.join(hls_dir, '720p')
    thumb_dir = os.path.join(working_dir or settings.MEDIA_ROOT, 'thumbnails')
    spr_dir   = os.path.join(working_dir or settings.MEDIA_ROOT, 'sprites')

    if use_s3:
        hls_dir  = os.path.join(working_dir, 'hls')
        dir_1080 = os.path.join(hls_dir, '1080p')
        dir_720  = os.path.join(hls_dir, '720p')
        thumb_dir = os.path.join(working_dir, 'thumbnails')
        spr_dir   = os.path.join(working_dir, 'sprites')
    else:
        hls_dir  = os.path.join(settings.MEDIA_ROOT, 'hls', str(video_id))
        dir_1080 = os.path.join(hls_dir, '1080p')
        dir_720  = os.path.join(hls_dir, '720p')
        thumb_dir = os.path.join(settings.MEDIA_ROOT, 'thumbnails')
        spr_dir   = os.path.join(settings.MEDIA_ROOT, 'sprites')

    for d in [dir_1080, dir_720, thumb_dir, spr_dir]:
        os.makedirs(d, exist_ok=True)

    try:
        # ── 1. ffprobe metadata ───────────────────────────────────────────────
        video.status = 'analyzing'
        video.save()

        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', input_path],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(probe.stdout)
        fmt = data.get('format', {})
        st  = data.get('streams', [])

        vstream  = next((s for s in st if s.get('codec_type') == 'video'), {})
        duration = float(fmt.get('duration', 0) or 0)
        video.duration = round(duration, 2)

        w, h = vstream.get('width'), vstream.get('height')
        if w and h:
            video.resolution = f"{w}x{h}"

        video.codec = vstream.get('codec_name', '').upper()

        fps_str = vstream.get('r_frame_rate', '')
        if '/' in fps_str:
            try:
                num, den = map(int, fps_str.split('/'))
                video.fps = f"{round(num / den, 2)} fps" if den > 0 else "—"
            except Exception:
                video.fps = "—"
        else:
            video.fps = f"{fps_str} fps" if fps_str else "—"

        bit_rate = float(fmt.get('bit_rate', 0) or vstream.get('bit_rate', 0) or 0)
        video.bitrate = f"{round(bit_rate / 1000000, 2)} Mbps" if bit_rate > 0 else "—"
        video.save()

        # ── 2. Encode BOTH HLS streams in a SINGLE ffmpeg pass ───────────────
        # Use filter_complex split so the video is decoded once.
        # Map only 0:a:0? (first audio only) to skip iPhone metadata/data tracks
        # that have codec 'none' and can't be decoded.
        video.status = 'transcoding_1080p'
        video.save()

        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-filter_complex',
            '[0:v]split[v1][v2];'
            '[v1]scale=trunc(oh*a/2)*2:1080[out1080];'
            '[v2]scale=trunc(oh*a/2)*2:720[out720]',

            # ── output 1: 1080p HLS ──
            '-map', '[out1080]', '-map', '0:a:0?',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'ultrafast',
            '-c:a', 'aac', '-b:a', '192k',
            '-hls_time', '6', '-hls_playlist_type', 'vod',
            '-hls_segment_filename', os.path.join(dir_1080, 'seg%03d.ts'),
            os.path.join(dir_1080, 'stream.m3u8'),

            # ── output 2: 720p HLS ──
            '-map', '[out720]', '-map', '0:a:0?',
            '-c:v', 'libx264', '-crf', '23', '-preset', 'ultrafast',
            '-c:a', 'aac', '-b:a', '128k',
            '-hls_time', '6', '-hls_playlist_type', 'vod',
            '-hls_segment_filename', os.path.join(dir_720, 'seg%03d.ts'),
            os.path.join(dir_720, 'stream.m3u8'),
        ])

        # ── 3. Master playlist ───────────────────────────────────────────────
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

        # ── 4. Thumbnail & sprite (two simple reliable passes) ───────────────
        video.status = 'generating_assets'
        video.save()

        thumb_abs  = os.path.join(thumb_dir, f'{video_id}.jpg')
        sprite_abs = os.path.join(spr_dir, f'{video_id}.jpg')
        thumb_at   = min(1.0, duration / 2.0) if duration > 0 else 0
        num_frames = max(1, math.ceil(duration / 5))
        cols       = min(10, num_frames)
        rows       = math.ceil(num_frames / cols)

        # Thumbnail
        _run([
            'ffmpeg', '-y', '-ss', str(thumb_at), '-i', input_path,
            '-map', '0:v:0',
            '-vframes', '1', '-vf', 'scale=1280:-2', '-q:v', '3',
            thumb_abs,
        ])

        # Sprite sheet
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-map', '0:v:0',
            '-vf', f'fps=1/5,scale=160:90,tile={cols}x{rows}',
            '-frames:v', '1', '-q:v', '4',
            sprite_abs,
        ])

        # ── 5. Parallel S3 uploads ───────────────────────────────────────────
        if use_s3:
            upload_tasks = []

            # Collect HLS files
            for root, _, files in os.walk(hls_dir):
                for file in files:
                    local_fpath = os.path.join(root, file)
                    rel = os.path.relpath(local_fpath, hls_dir)
                    s3_path = f'hls/{video_id}/{rel}'
                    with open(local_fpath, 'rb') as f:
                        upload_tasks.append((s3_path, f.read()))

            # Thumbnail
            if os.path.exists(thumb_abs):
                with open(thumb_abs, 'rb') as f:
                    upload_tasks.append((f'thumbnails/{video_id}.jpg', f.read()))

            # Sprite
            if os.path.exists(sprite_abs):
                with open(sprite_abs, 'rb') as f:
                    upload_tasks.append((f'sprites/{video_id}.jpg', f.read()))

            # Metadata JSON — includes password hash so user can be restored on rebuild
            meta_data = {
                'title': video.title,
                'owner_username': video.owner.username if video.owner else 'demo_guest_user',
                'owner_password_hash': video.owner.password if video.owner else '',
                'duration': video.duration,
                'fps': video.fps,
                'codec': video.codec,
                'resolution': video.resolution,
                'bitrate': video.bitrate,
                'original_filename': os.path.basename(video.original_file.name),
            }
            upload_tasks.append((
                f'hls/{video_id}/metadata.json',
                json.dumps(meta_data).encode('utf-8'),
            ))

            # Fire all uploads concurrently (8 threads max)
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_s3_upload, path, data): path for path, data in upload_tasks}
                for future in as_completed(futures):
                    exc = future.exception()
                    if exc:
                        print(f"[S3 Upload] failed for {futures[future]}: {exc}")

        # ── 6. Mark done ─────────────────────────────────────────────────────
        video.hls_master.name = f'hls/{video_id}/master.m3u8'
        video.thumbnail.name  = f'thumbnails/{video_id}.jpg'
        video.sprite_sheet.name = f'sprites/{video_id}.jpg'
        video.status = 'done'
        video.save()

        if tmp_dir_obj:
            try:
                tmp_dir_obj.cleanup()
            except Exception:
                pass

        return "Success"

    except subprocess.CalledProcessError as e:
        video.status = 'failed'
        video.save()
        traceback.print_exc()
        if tmp_dir_obj:
            try:
                tmp_dir_obj.cleanup()
            except Exception:
                pass
        err_msg = e.stderr.decode(errors='replace') if e.stderr else str(e)
        print(f"[FFmpeg] failed for video {video_id}:\n{err_msg}")
        return "Failed"

    except Exception as e:
        video.status = 'failed'
        video.save()
        traceback.print_exc()
        if tmp_dir_obj:
            try:
                tmp_dir_obj.cleanup()
            except Exception:
                pass
        print(f"[Worker] failed for video {video_id}: {e}")
        return "Failed"
