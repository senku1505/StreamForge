# videos/views.py
import jwt
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import authentication
from .models import Video
from .serializers import VideoSerializer
from .tasks import process_video

# simple jwt auth for drf
class JWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth = request.headers.get('Authorization')
        if not auth or ' ' not in auth:
            return None
        try:
            prefix, token = auth.split(' ')
            if prefix.lower() != 'bearer':
                return None
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            user = User.objects.get(id=payload['user_id'])
            return (user, token)
        except Exception:
            return None

def make_token(user):
    # sign token valid for 7 days
    payload = {
        'user_id': user.id,
        'username': user.username,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


class SignupView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = request.data.get('email', '').strip()
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()

        # strict payload limits to avoid spam/attacks
        if not email or not username or not password:
            return Response({"error": "all fields are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        if not (6 <= len(username) <= 20):
            return Response({"error": "username must be 6-20 chars"}, status=status.HTTP_400_BAD_REQUEST)
            
        if not (6 <= len(password) <= 20):
            return Response({"error": "password must be 6-20 chars"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({"error": "username already taken"}, status=status.HTTP_400_BAD_REQUEST)

        # create new user pg
        user = User.objects.create_user(username=username, email=email, password=password)
        return Response({"token": make_token(user), "username": user.username}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()

        if not (6 <= len(username) <= 20) or not (6 <= len(password) <= 20):
            return Response({"error": "credentials validation failed (6-20 chars)"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)
        if not user:
            return Response({"error": "invalid username or password"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({"token": make_token(user), "username": user.username})


class GuestLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        # find or make demo user
        user, created = User.objects.get_or_create(
            username='demo_guest_user',
            defaults={'email': 'demo@streamforge.com'}
        )
        if created:
            user.set_password('demo_guest_password_123')
            user.save()

        return Response({"token": make_token(user), "username": user.username})


class VideoListView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def get(self, request):
        # grab all videos for public feed
        videos = Video.objects.all()
        serializer = VideoSerializer(videos, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        # check jwt user
        if not request.user.is_authenticated:
            return Response({"error": "login required to upload"}, status=status.HTTP_401_UNAUTHORIZED)
            
        serializer = VideoSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            video = serializer.save(owner=request.user)
            process_video.delay(video.id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VideoDetailView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def get(self, request, pk):
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

        # only owner can delete their files
        if video.owner and video.owner != request.user:
            return Response({"error": "you do not own this video"}, status=status.HTTP_403_FORBIDDEN)
            
        video.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, pk):
        try:
            video = Video.objects.get(pk=pk)
        except Video.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # only owner can edit their files
        if video.owner and video.owner != request.user:
            return Response({"error": "you do not own this video"}, status=status.HTTP_403_FORBIDDEN)

        serializer = VideoSerializer(video, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PersonalVideoListView(APIView):
    # api endpoint for custom personal pool
    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "login required"}, status=status.HTTP_401_UNAUTHORIZED)
        videos = Video.objects.filter(owner=request.user)
        serializer = VideoSerializer(videos, many=True, context={'request': request})
        return Response(serializer.data)