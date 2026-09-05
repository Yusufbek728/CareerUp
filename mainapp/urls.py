from django.urls import path, include
from rest_framework import routers

from .views import (
    home_view,
    JobViewSet,
    ResumeViewSet,
    InternshipViewSet,
    job_detail,
    internship_detail,
    resume_detail,
    create_listing,
)

router = routers.DefaultRouter()
router.register(r'jobs', JobViewSet)
router.register(r'resumes', ResumeViewSet)
router.register(r'internships', InternshipViewSet)

urlpatterns = [
    path('', home_view, name='home'),
    path('jobs/<int:pk>/', job_detail, name='job_detail'),
    path('internships/<int:pk>/', internship_detail, name='internship_detail'),
    path('resumes/<int:pk>/', resume_detail, name='resume_detail'),
    path('create/<str:listing_type>/', create_listing, name='create_listing'),
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]