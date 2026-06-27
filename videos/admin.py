# videos/admin.py
import os
import shutil

from django.contrib import admin
from .models import Video

# ── Admin site branding ───────────────────────────────────────────────
admin.site.site_header = "StreamForge"
admin.site.site_title  = "StreamForge Admin"
admin.site.index_title = "Video Management"


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display    = ('title', 'status', 'duration_display', 'resolution', 'fps', 'codec', 'original_size', 'created_at')
    list_filter     = ('status', 'created_at')
    search_fields   = ('title',)
    readonly_fields = ('created_at', 'duration', 'status', 'hls_master',
                       'thumbnail', 'sprite_sheet', 'gif_preview',
                       'resolution', 'codec', 'fps', 'bitrate')
    actions = ['delete_with_files']

    # ── Custom columns ────────────────────────────────────────────────
    @admin.display(description='Duration')
    def duration_display(self, obj):
        if obj.duration:
            m = int(obj.duration // 60)
            s = int(obj.duration % 60)
            return f"{m}:{s:02d}"
        return "—"

    @admin.display(description='Raw Size')
    def original_size(self, obj):
        try:
            if obj.original_file and obj.original_file.size:
                return f"{obj.original_file.size / (1024 * 1024):.2f} MB"
        except Exception:
            pass
        return "N/A"

    # ── Custom delete action ──────────────────────────────────────────
    @admin.action(description="Delete selected videos (with all files)")
    def delete_with_files(self, request, queryset):
        count = 0
        for video in queryset:
            video.delete()
            count += 1
        self.message_user(
            request,
            f"Successfully deleted {count} video(s) and all associated files.",
        )

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.delete()

