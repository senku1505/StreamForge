from django.db import models
class Video(models.Model):
    title = models.CharField(max_length=255)
    original_file = models.FileField(upload_to='raw/')
    video_720 = models.FileField(upload_to='processed/720p/', null=True, blank=True)
    video_480 = models.FileField(upload_to='processed/480p/', null=True, blank=True)
    thumbnail = models.ImageField(upload_to='thumbnails/', null=True, blank=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title