"""
URL configuration for streamforge project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from .views import VideoListView, VideoDetailView

urlpatterns = [
    # Frontend UI Routes
    path('upload/', TemplateView.as_view(template_name="upload.html"), name='ui-upload'),
    path('library/', TemplateView.as_view(template_name="library.html"), name='ui-library'),
    path('player/', TemplateView.as_view(template_name="player.html"), name='ui-player'),
    
    # API Routes
    path('api/videos/', VideoListView.as_view(), name='api-video-list'),
    path('api/videos/<int:pk>/', VideoDetailView.as_view(), name='api-video-detail'),
]


# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    