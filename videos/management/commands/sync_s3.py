from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from videos.models import Video
import json
import os
from datetime import datetime, timezone

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '--wipe',
            action='store_true',
            help='Wipe all database records and S3 bucket files immediately',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'USE_S3', False):
            self.stdout.write("S3 is not enabled (USE_S3 is False). Skipping sync.")
            return

        # If --wipe is set, do the wipe and exit
        if options['wipe']:
            self.stdout.write("==> Wiping database and S3/R2 storage immediately...")
            try:
                bucket = default_storage.bucket
                bucket.objects.all().delete()
                Video.objects.all().delete()
                # Re-save cleanup metadata with current time
                cleanup_meta_key = 'cleanup_metadata.json'
                if default_storage.exists(cleanup_meta_key):
                    default_storage.delete(cleanup_meta_key)
                now = datetime.now(timezone.utc)
                default_storage.save(cleanup_meta_key, ContentFile(json.dumps({'last_cleanup': now.isoformat()}).encode('utf-8')))
                self.stdout.write(self.style.SUCCESS("Wipe completed successfully. Storage is empty."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to wipe storage: {e}"))
            return

        self.stdout.write("==> Running S3 database synchronization and cleanup check...")

        # 1. Perform 10-day cleanup check
        self.check_and_perform_periodic_cleanup()

        # 2. Synchronize database with S3 metadata
        self.sync_database_with_s3()

    def check_and_perform_periodic_cleanup(self):
        cleanup_meta_key = 'cleanup_metadata.json'
        now = datetime.now(timezone.utc)
        perform_cleanup = False

        try:
            if default_storage.exists(cleanup_meta_key):
                with default_storage.open(cleanup_meta_key, 'rb') as f:
                    content = f.read()
                    if isinstance(content, bytes):
                        content = content.decode('utf-8')
                    data = json.loads(content)
                    last_cleanup = datetime.fromisoformat(data['last_cleanup'])
                    # 10 days = 10 * 24 * 3600 seconds
                    delta_seconds = (now - last_cleanup).total_seconds()
                    days_passed = delta_seconds / (24 * 3600)
                    self.stdout.write(f"Last cleanup was {days_passed:.2f} days ago.")
                    if delta_seconds >= 10 * 24 * 3600:
                        perform_cleanup = True
            else:
                self.stdout.write("No cleanup metadata found. Initializing metadata file.")
                # Save initial metadata file so we start the 10-day count from now
                default_storage.save(cleanup_meta_key, ContentFile(json.dumps({'last_cleanup': now.isoformat()}).encode('utf-8')))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Failed to check cleanup status: {e}"))

        if perform_cleanup:
            self.stdout.write(self.style.NOTICE("10 days reached! Wiping R2 storage and database..."))
            try:
                bucket = default_storage.bucket
                # Delete all objects in bucket
                bucket.objects.all().delete()
                # Clear all videos from database
                Video.objects.all().delete()
                # Re-save cleanup metadata with current time
                default_storage.delete(cleanup_meta_key)
                default_storage.save(cleanup_meta_key, ContentFile(json.dumps({'last_cleanup': now.isoformat()}).encode('utf-8')))
                self.stdout.write(self.style.SUCCESS("Cleanup completed successfully. Storage is empty."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed during cleanup wipe: {e}"))

    def sync_database_with_s3(self):
        try:
            bucket = default_storage.bucket
            
            # Find all hls/<id>/metadata.json keys in S3
            paginator = bucket.meta.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket.name, Prefix='hls/')
            
            s3_video_ids = set()
            metadata_keys = []
            
            for page in pages:
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('/metadata.json'):
                        metadata_keys.append(key)

            for key in metadata_keys:
                parts = key.split('/')
                if len(parts) >= 3:
                    try:
                        s3_video_ids.add(int(parts[1]))
                    except ValueError:
                        pass

            db_video_ids = set(Video.objects.values_list('id', flat=True))
            missing_ids = s3_video_ids - db_video_ids

            if not missing_ids:
                self.stdout.write(self.style.SUCCESS("Database is already up to date with S3."))
                return

            self.stdout.write(f"Found {len(missing_ids)} videos on S3 missing from local DB. Restoring...")

            # Re-create missing videos in DB
            for vid_id in missing_ids:
                meta_key = f'hls/{vid_id}/metadata.json'
                try:
                    with default_storage.open(meta_key, 'rb') as f:
                        content = f.read()
                        if isinstance(content, bytes):
                            content = content.decode('utf-8')
                        meta = json.loads(content)

                    owner_username = meta.get('owner_username', 'demo_guest_user')
                    owner, created = User.objects.get_or_create(username=owner_username)
                    if created:
                        # Restore password hash if saved, otherwise use env fallback
                        saved_hash = meta.get('owner_password_hash')
                        fallback_pass = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
                        if saved_hash:
                            owner.password = saved_hash
                            owner.save()
                        elif fallback_pass:
                            owner.set_password(fallback_pass)
                            owner.save()
                        # else: unusable password — user must reset via admin

                    original_filename = meta.get('original_filename', 'video.mp4')

                    Video.objects.create(
                        id=vid_id,
                        title=meta.get('title', 'Restored Video'),
                        owner=owner,
                        duration=meta.get('duration'),
                        fps=meta.get('fps'),
                        codec=meta.get('codec'),
                        resolution=meta.get('resolution'),
                        bitrate=meta.get('bitrate'),
                        status='done',
                        original_file=f'raw/{original_filename}',
                        hls_master=f'hls/{vid_id}/master.m3u8',
                        thumbnail=f'thumbnails/{vid_id}.jpg',
                        sprite_sheet=f'sprites/{vid_id}.jpg'
                    )
                    self.stdout.write(self.style.SUCCESS(f"Restored video {vid_id} ('{meta.get('title')}')"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Failed to restore video {vid_id}: {e}"))

        except Exception as e:
            import traceback
            self.stdout.write(self.style.ERROR(f"Error scanning S3 bucket: {e}\n{traceback.format_exc()}"))
