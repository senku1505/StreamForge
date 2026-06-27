# videos/views.py
from .tasks import process_video
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Video
from .serializers import VideoSerializer


class VideoListView(APIView):
    # disable auth stuff so deletion doesnt get blocked by csrf
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # grab all videos
        videos = Video.objects.all()
        serializer = VideoSerializer(videos, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        # handle new video upload
        serializer = VideoSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            video = serializer.save()
            process_video.delay(video.id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VideoDetailView(APIView):
    # public endpoints are fine for dev
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        # fetch single vid
        try:
            video = Video.objects.get(pk=pk)
        except Video.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data)

    def delete(self, request, pk):
        try:
            video = Video.objects.get(pk=pk)
        except Video.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        video.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)