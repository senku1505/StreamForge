import os
import subprocess
import json
import math
from celery import shared_task
from django.conf import settings
from .models import Video

def _run(cmd):
    # runs shell stuff
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, stderr=result.stderr)


def check_and_enforce_storage_limit():
    # keep total storage under 5gb so disk doesnt blow up
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
                        
    limit = 5 * 1024 * 1024 * 1024 # 5 GB
    if total_size > limit:
        # delete oldest 2 vids
        oldest = Video.objects.all().order_by('created_at')[:2]
        for video in oldest:
            try:
                video.delete()
            except Exception as e:
                print(f"[Quota] delete failed for {video.id}: {e}")


from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import tempfile
import shutil

@shared_task
def process_video(video_id):
    # check space first if running locally
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

    # We will use a temporary directory if S3 is active
    if use_s3:
        tmp_dir_obj = tempfile.TemporaryDirectory()
        working_dir = tmp_dir_obj.name
        input_filename = os.path.basename(video.original_file.name)
        input_path = os.path.join(working_dir, input_filename)
        
        # Download original file from S3 to temp directory
        try:
            with default_storage.open(video.original_file.name, 'rb') as source:
                with open(input_path, 'wb') as dest:
                    shutil.copyfileobj(source, dest)
        except Exception as e:
            tmp_dir_obj.cleanup()
            raise RuntimeError(f"Failed to download original file from S3: {e}")
            
        hls_dir = os.path.join(working_dir, 'hls')
        dir_1080 = os.path.join(hls_dir, '1080p')
        dir_720 = os.path.join(hls_dir, '720p')
        thumb_dir = os.path.join(working_dir, 'thumbnails')
        spr_dir = os.path.join(working_dir, 'sprites')
    else:
        tmp_dir_obj = None
        working_dir = None
        input_path = video.original_file.path
        media_root = settings.MEDIA_ROOT
        hls_dir = os.path.join(media_root, 'hls', str(video_id))
        dir_1080 = os.path.join(hls_dir, '1080p')
        dir_720 = os.path.join(hls_dir, '720p')
        thumb_dir = os.path.join(media_root, 'thumbnails')
        spr_dir = os.path.join(media_root, 'sprites')

    for d in [dir_1080, dir_720, thumb_dir, spr_dir]:
        os.makedirs(d, exist_ok=True)

    try:
        # extract stats with ffprobe
        video.status = 'analyzing'
        video.save()

        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', input_path],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(probe.stdout)
        fmt = data.get('format', {})
        st = data.get('streams', [])
        
        vstream = next((s for s in st if s.get('codec_type') == 'video'), {})
        
        duration = float(fmt.get('duration', 0) or 0)
        video.duration = round(duration, 2)
        
        w = vstream.get('width')
        h = vstream.get('height')
        if w and h:
            video.resolution = f"{w}x{h}"
            
        video.codec = vstream.get('codec_name', '').upper()
        
        fps_str = vstream.get('r_frame_rate', '')
        if '/' in fps_str:
            try:
                num, den = map(int, fps_str.split('/'))
                if den > 0:
                    video.fps = f"{round(num / den, 2)} fps"
            except Exception:
                video.fps = "—"
        else:
            video.fps = f"{fps_str} fps" if fps_str else "—"
            
        bit_rate = float(fmt.get('bit_rate', 0) or vstream.get('bit_rate', 0) or 0)
        if bit_rate > 0:
            video.bitrate = f"{round(bit_rate / 1000000, 2)} Mbps"
        else:
            video.bitrate = "—"
            
        video.save()

        # encode HLS 1080p
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

        # encode HLS 720p
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

        # build playlist file
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

        # build assets (thumbs & tiles)
        video.status = 'generating_assets'
        video.save()
        
        thumb_at = max(1.0, duration * 0.1)
        thumb_abs = os.path.join(thumb_dir, f'{video_id}.jpg')
        _run([
            'ffmpeg', '-y', '-ss', str(thumb_at), '-i', input_path,
            '-vframes', '1', '-vf', 'scale=1280:-2', '-q:v', '3',
            thumb_abs,
        ])

        num_frames = max(1, math.ceil(duration / 5))
        cols = min(10, num_frames)
        rows = math.ceil(num_frames / cols)
        sprite_abs = os.path.join(spr_dir, f'{video_id}.jpg')
        _run([
            'ffmpeg', '-y', '-i', input_path,
            '-vf', f'fps=1/5,scale=160:90,tile={cols}x{rows}',
            '-frames:v', '1', '-q:v', '4',
            sprite_abs,
        ])

        # If using S3, upload files to S3
        if use_s3:
            # 1. Upload HLS files
            for root, _, files in os.walk(hls_dir):
                for file in files:
                    local_fpath = os.path.join(root, file)
                    rel_to_hls = os.path.relpath(local_fpath, hls_dir)
                    s3_path = f'hls/{video_id}/{rel_to_hls}'
                    with open(local_fpath, 'rb') as f:
                        if default_storage.exists(s3_path):
                            default_storage.delete(s3_path)
                        default_storage.save(s3_path, f)

            # 2. Upload thumbnail
            s3_thumb_path = f'thumbnails/{video_id}.jpg'
            with open(thumb_abs, 'rb') as f:
                if default_storage.exists(s3_thumb_path):
                    default_storage.delete(s3_thumb_path)
                default_storage.save(s3_thumb_path, f)

            # 3. Upload sprite
            s3_sprite_path = f'sprites/{video_id}.jpg'
            with open(sprite_abs, 'rb') as f:
                if default_storage.exists(s3_sprite_path):
                    default_storage.delete(s3_sprite_path)
                default_storage.save(s3_sprite_path, f)

        # update db paths & finish
        video.hls_master.name = f'hls/{video_id}/master.m3u8'
        video.thumbnail.name = f'thumbnails/{video_id}.jpg'
        video.sprite_sheet.name = f'sprites/{video_id}.jpg'
        video.status = 'done'
        video.save()

        # Clean up temporary directory if we created one
        if tmp_dir_obj:
            try:
                tmp_dir_obj.cleanup()
            except Exception:
                pass

        return "Success"

    except subprocess.CalledProcessError as e:
        video.status = 'failed'
        video.save()
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
        if tmp_dir_obj:
            try:
                tmp_dir_obj.cleanup()
            except Exception:
                pass
        print(f"[Worker] failed for video {video_id}: {e}")
        return "Failed"
