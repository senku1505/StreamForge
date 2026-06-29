# videos/admin.py
import os
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from .models import Video

# streamforge branding in admin pg
admin.site.site_header = "StreamForge"
admin.site.site_title  = "StreamForge Admin"
admin.site.index_title = "Video Management"

admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(DefaultUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'password', 'is_staff')


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    # list columns
    list_display    = ('title', 'status', 'duration_display', 'resolution', 'fps', 'codec', 'original_size', 'created_at')
    list_filter     = ('status', 'created_at')
    search_fields   = ('title',)
    
    # disable editing for auto generated stats
    readonly_fields = ('created_at', 'duration', 'status', 'hls_master',
                       'thumbnail', 'sprite_sheet', 'resolution', 'codec', 'fps', 'bitrate')
    actions = ['delete_with_files']

    @admin.display(description='Duration')
    def duration_display(self, obj):
        # formatted duration
        return obj.duration_formatted or "—"

    @admin.display(description='Raw Size')
    def original_size(self, obj):
        # convert bytes to mb lol
        try:
            if obj.original_file and obj.original_file.size:
                return f"{obj.original_file.size / (1024 * 1024):.2f} MB"
        except Exception:
            pass
        return "N/A"

    @admin.action(description="Delete selected videos (with all files)")
    def delete_with_files(self, request, queryset):
        # bulk delete that actually triggers custom delete() cleanups
        count = 0
        for video in queryset:
            video.delete()
            count += 1
        self.message_user(
            request,
            f"Successfully deleted {count} video(s) and all associated files.",
        )

    def delete_queryset(self, request, queryset):
        # loop n delete
        for obj in queryset:
            obj.delete()
