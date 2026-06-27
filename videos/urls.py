# videos/urls.py
from django.urls import path
from django.views.generic import TemplateView
from .views import VideoListView, VideoDetailView

urlpatterns = [
    # Frontend UI Routes
    path('upload/',  TemplateView.as_view(template_name="upload.html"),  name='ui-upload'),
    path('library/', TemplateView.as_view(template_name="library.html"), name='ui-library'),
    path('player/',  TemplateView.as_view(template_name="player.html"),  name='ui-player'),
    path('about/',   TemplateView.as_view(template_name="about.html"),   name='ui-about'),

    # API Routes
    path('api/videos/',         VideoListView.as_view(),   name='api-video-list'),
    path('api/videos/<int:pk>/', VideoDetailView.as_view(), name='api-video-detail'),
]