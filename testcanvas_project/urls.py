from django.contrib import admin
from django.urls import path, include

# Rebrand the Django admin site: replace the default "Django administration"
# wording with the project name across the header, browser title and index.
admin.site.site_header = "Test Canvas"
admin.site.site_title = "Test Canvas"
admin.site.index_title = "Test Canvas administration"

urlpatterns = [
    # rest framework browsable API
    path("api-auth/", include("rest_framework.urls")),
    path('admin/', admin.site.urls),
    path("", include('mcp_server.urls')),  # endpoint for mcp server /mcp
    path('', include('testcanvas.urls')),
]
