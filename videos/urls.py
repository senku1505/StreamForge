from django.urls import path
from django.views.generic import TemplateView
from .views import (
    VideoListView, VideoDetailView, PersonalVideoListView,
    SignupView, LoginView, GuestLoginView
)

# route mapping for pages & APIs
urlpatterns = [
    # Frontend UI Routes
    path('',           TemplateView.as_view(template_name="about.html"),      name='ui-home'),
    path('login/',     TemplateView.as_view(template_name="login.html"),      name='ui-login'),
    path('upload/',    TemplateView.as_view(template_name="upload.html"),     name='ui-upload'),
    path('library/',   TemplateView.as_view(template_name="library.html"),    name='ui-library'),
    path('my-videos/', TemplateView.as_view(template_name="my_videos.html"),  name='ui-my-videos'),
    path('player/',    TemplateView.as_view(template_name="player.html"),     name='ui-player'),
    path('about/',     TemplateView.as_view(template_name="about.html"),      name='ui-about'),

    # API Routes
    path('api/signup/',         SignupView.as_view(),      name='api-signup'),
    path('api/login/',          LoginView.as_view(),       name='api-login'),
    path('api/login/guest/',    GuestLoginView.as_view(),  name='api-login-guest'),
    path('api/videos/',         VideoListView.as_view(),   name='api-video-list'),
    path('api/videos/personal/', PersonalVideoListView.as_view(), name='api-video-personal'),
    path('api/videos/<int:pk>/', VideoDetailView.as_view(), name='api-video-detail'),
]