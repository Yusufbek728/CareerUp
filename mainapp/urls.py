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
    choose_role,
    edit_listing,
    login_view,
    logout_view,
    my_listings,
    register_view,
    RegistrationAPIView,
    super_admin,
    super_admin_edit_listing,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

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
    path('choose-role/', choose_role, name='choose_role'),
    path('edit/<str:listing_type>/<int:pk>/', edit_listing, name='edit_listing'),
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('my-listings/', my_listings, name='my_listings'),
    path('super_admin', super_admin, name='super_admin'),
    path('super_admin/', super_admin),
    path('super_admin/<str:listing_type>/<int:pk>/edit/', super_admin_edit_listing, name='super_admin_edit_listing'),
    path('api/', include(router.urls)),
    path('api/register/', RegistrationAPIView.as_view(), name='api_register'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]