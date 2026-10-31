"""webodm URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.10/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import re_path, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
import os

from django.urls import include, re_path
from django.urls import re_path
from django.contrib import admin
from . import settings
from django.views.static import serve

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

admin.site.site_header = 'WebODM Administration'

schema_view = get_schema_view(
   openapi.Info(
      title="WebODM API",
      default_version='v1.0.0',
      description="WebODM API",
      #terms_of_service="",
      #contact=openapi.Contact(email=""),
   ),
   public=True,
   permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    re_path(r'^', include('app.urls')),
    re_path(r'^', include('django.contrib.auth.urls')),
    re_path(r'^admin/', admin.site.urls),
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    re_path(r'^swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    re_path(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]

if settings.DEBUG or settings.FORCE_MEDIA_STATICFILES:
    urlpatterns += [
        # Expose imagekit generated files and settings file uploads
        re_path(r'^media/CACHE/(?P<path>.*)$', serve, {
            'document_root': os.path.join(settings.MEDIA_ROOT, 'CACHE')
        }),
        re_path(r'^media/settings/(?P<path>.*)$', serve, {
            'document_root': os.path.join(settings.MEDIA_ROOT, 'settings')
        }),

    ]

#from django.contrib.staticfiles.urls import staticfiles_urlpatterns
#urlpatterns += staticfiles_urlpatterns()

