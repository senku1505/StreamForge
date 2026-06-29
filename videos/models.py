from django.db import models
from django.contrib.auth.models import User

class Video(models.Model):
    STATUS_CHOICES = [
        ('pending',          'Pending'),
        ('analyzing',        'Analyzing'),
        ('transcoding_1080p','Transcoding 1080p'),
        ('transcoding_720p', 'Transcoding 720p'),
        ('generating_assets','Generating Assets'),
        ('done',             'Done'),
        ('failed',           'Failed'),
    ]

    title         = models.CharField(max_length=255)
    owner         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='videos', null=True, blank=True)
    original_file = models.FileField(upload_to='raw/')
    hls_master    = models.FileField(upload_to='hls/', null=True, blank=True)
    thumbnail     = models.ImageField(upload_to='thumbnails/', null=True, blank=True)
    sprite_sheet  = models.ImageField(upload_to='sprites/',    null=True, blank=True)
    duration      = models.FloatField(null=True, blank=True)   # secs
    fps           = models.CharField(max_length=20, null=True, blank=True)
    codec         = models.CharField(max_length=50, null=True, blank=True)
    resolution    = models.CharField(max_length=50, null=True, blank=True)
    bitrate       = models.CharField(max_length=50, null=True, blank=True)
    status        = models.CharField(max_length=30, default='pending', choices=STATUS_CHOICES)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def duration_formatted(self):
        # format duration to MIN:SS
        if not self.duration:
            return None
        m = int(self.duration // 60)
        s = int(self.duration % 60)
        return f"{m}:{s:02d}"

    def delete(self, *args, **kwargs):
        import shutil
        import os
        from django.conf import settings
        from django.core.files.storage import default_storage

        # wipe files when db row is deleted
        try:
            if getattr(settings, 'USE_S3', False):
                # Delete HLS folder from S3
                try:
                    bucket = default_storage.bucket
                    bucket.objects.filter(Prefix=f'hls/{self.id}/').delete()
                except Exception as e:
                    print(f"Failed to delete S3 HLS folder: {e}")
            else:
                hls_dir = os.path.join(settings.MEDIA_ROOT, 'hls', str(self.id))
                if os.path.exists(hls_dir):
                    shutil.rmtree(hls_dir, ignore_errors=True)
        except Exception:
            pass

        # delete other media assets
        for field in (self.thumbnail, self.sprite_sheet, self.original_file):
            try:
                if field and field.name:
                    field.delete(save=False)
            except Exception:
                pass

        super().delete(*args, **kwargs)