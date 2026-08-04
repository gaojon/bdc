"""Admin configuration for accounts."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from accounts.models import LoginRecord, Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class CustomUserAdmin(UserAdmin):
    inlines = [ProfileInline]


@admin.register(LoginRecord)
class LoginRecordAdmin(admin.ModelAdmin):
    list_display = ("user", "logged_in_at", "ip_address")
    list_filter = ("logged_in_at",)
    search_fields = ("user__username",)
    readonly_fields = ("logged_in_at",)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
