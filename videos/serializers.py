# videos/serializers.py
from rest_framework import serializers
from .models import Video

class VideoSerializer(serializers.ModelSerializer):
    original_size_formatted = serializers.SerializerMethodField()
    owner_username = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model = Video
        fields = '__all__'

    def get_original_size_formatted(self, obj):
        # convert original size to mb
        try:
            if obj.original_file and obj.original_file.size:
                return f"{obj.original_file.size / (1024 * 1024):.2f} MB"
        except Exception:
            pass
        return "—"

    def validate_original_file(self, value):
        # max size 500mb limit check
        limit = 500 * 1024 * 1024
        if value.size > limit:
            raise serializers.ValidationError("File size exceeds 500MB limit.")
        return value