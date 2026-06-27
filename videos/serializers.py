from rest_framework import serializers
from .models import Video

class VideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Video
        fields = '__all__'

    def validate_original_file(self, value):
        limit = 500 * 1024 * 1024
        if value.size > limit:
            raise serializers.ValidationError("File size cannot exceed 500MB.")
        return value

        