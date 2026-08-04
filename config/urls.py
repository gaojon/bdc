"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from accounts.admin_dashboard import get_urls as dashboard_urls

urlpatterns = [
    path("admin/", include((dashboard_urls(), "dashboard"))),
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("bank/", include("wordbank.urls")),
    path("", include("learning.urls")),
]
