from django.urls import path, include
from rest_framework import routers
from .views import JobViewSet, ResumeViewSet, InternshipViewSet
    

router = routers.DefaultRouter()
router.register(r"jobs", JobViewSet)
router.register(r"resumes", ResumeViewSet)
router.register(r"internships", InternshipViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
]