# videos/admin.py
from django.contrib import admin
from .models import Video

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'original_size', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title',)

    def original_size(self, obj):
        if obj.original_file and hasattr(obj.original_file, 'size'):
            # Convert bytes to MB
            return f"{obj.original_file.size / (1024 * 1024):.2f} MB"
        return "N/A"
    original_size.short_description = 'Raw File Size'