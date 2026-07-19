from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # rest framework browsable API
    path("api-auth/", include("rest_framework.urls")),
    path('admin/', admin.site.urls),
    path("", include('mcp_server.urls')),  # endpoint for mcp server /mcp
    path('', include('testcanvas.urls')),
]
