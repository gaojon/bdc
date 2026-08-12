"""Account views: login, logout, profile."""

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import LoginRecord


def get_client_ip(request) -> str:
    """Return the real client IP, honoring the nginx -> gunicorn reverse proxy.

    Gunicorn 26 no longer rewrites REMOTE_ADDR from X-Forwarded-For, so behind
    nginx REMOTE_ADDR is always 127.0.0.1. nginx overwrites X-Real-IP with the
    client's real address on every request (so it cannot be spoofed), and
    appends to X-Forwarded-For — take the rightmost entry as authoritative.
    """
    ip = request.META.get("HTTP_X_REAL_IP")
    if ip:
        return ip
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def login_view(request):
    """Handle user login."""
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Record login
            LoginRecord.objects.create(
                user=user,
                ip_address=get_client_ip(request),
            )
            next_url = request.GET.get("next", "/")
            return redirect(next_url)
        messages.error(request, "Invalid username or password.")
    return render(request, "accounts/login.html")


def logout_view(request):
    """Handle user logout."""
    if request.user.is_authenticated:
        logout(request)
    return redirect("accounts:login")


@login_required
def profile_view(request):
    """View and edit user profile."""
    if request.method == "POST":
        profile = request.user.profile
        profile.nickname = request.POST.get("nickname", "")
        profile.english_level = request.POST.get("english_level", profile.english_level)
        complexity = request.POST.get("sentence_complexity")
        if complexity and complexity.isdigit():
            profile.sentence_complexity = int(complexity)
        goal = request.POST.get("daily_word_goal")
        if goal and goal.isdigit():
            profile.daily_word_goal = int(goal)
        article_len = request.POST.get("article_length")
        if article_len and article_len.isdigit():
            profile.article_length = max(100, min(600, int(article_len)))
        profile.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")

    return render(request, "accounts/profile.html")
