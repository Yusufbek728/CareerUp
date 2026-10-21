"""
URL configuration for config project.
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import Http404
from django.urls import path, include, re_path
from django.views.static import serve
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

schema_view = get_schema_view(
    openapi.Info(
        title='CareerUp API',
        default_version='v1',
        description='CareerUp jobs, resumes and internships API',
        terms_of_service='https://www.google.com/policies/terms/',
        contact=openapi.Contact(email='contact@snippets.local'),
        license=openapi.License(name='BSD License'),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

def superuser_only(view):
    # 404 instead of 403 so the API docs' existence isn't revealed to everyone else.
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_active and request.user.is_superuser):
            raise Http404
        return view(request, *args, **kwargs)
    return wrapped


urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('', include('chat.urls')),
    path('', include('mainapp.urls')),
    path('swagger<format>/', superuser_only(schema_view.without_ui(cache_timeout=0)), name='schema-json'),
    path('swagger/', superuser_only(schema_view.with_ui('swagger', cache_timeout=0)), name='schema-swagger-ui'),
    path('redoc/', superuser_only(schema_view.with_ui('redoc', cache_timeout=0)), name='schema-redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
