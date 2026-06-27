from django.db import models


class Video(models.Model):
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('processing', 'Processing'),
        ('done',       'Done'),
        ('failed',     'Failed'),
    ]

    title         = models.CharField(max_length=255)
    original_file = models.FileField(upload_to='raw/')
    hls_master    = models.FileField(upload_to='hls/', null=True, blank=True)
    thumbnail     = models.ImageField(upload_to='thumbnails/', null=True, blank=True)
    sprite_sheet  = models.ImageField(upload_to='sprites/',    null=True, blank=True)
    duration      = models.FloatField(null=True, blank=True)   # seconds
    status        = models.CharField(max_length=20, default='pending', choices=STATUS_CHOICES)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def duration_formatted(self):
        """Return duration as M:SS string."""
        if not self.duration:
            return None
        m = int(self.duration // 60)
        s = int(self.duration % 60)
        return f"{m}:{s:02d}"

    def delete(self, *args, **kwargs):
        import shutil
        import os
        from django.conf import settings

        # Clean up files on disk
        try:
            hls_dir = os.path.join(settings.MEDIA_ROOT, 'hls', str(self.id))
            if os.path.exists(hls_dir):
                shutil.rmtree(hls_dir, ignore_errors=True)
        except Exception:
            pass

        # Remove individual media files
        for field in (self.thumbnail, self.sprite_sheet, self.original_file):
            try:
                if field and field.name:
                    field.delete(save=False)
            except Exception:
                pass

        super().delete(*args, **kwargs)