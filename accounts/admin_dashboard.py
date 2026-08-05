"""Admin dashboard view showing system stats and user activity."""

import os
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils import timezone

from accounts.models import LoginRecord, Profile
from learning.models import Article, DailyUsage, LearningActivity, Quiz, UserWordStatus
from utils.config import get_config
from utils.constants import WordStatus
from wordbank.models import Word, WordBank


@login_required
def dashboard_view(request):
    """System statistics dashboard (superuser only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("learning:index")

    today = date.today()
    week_ago = today - timedelta(days=7)

    # DB disk usage
    db_path = settings.DATABASES["default"]["NAME"]
    db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    db_size_mb = db_size_bytes / (1024 * 1024)

    # User counts
    total_users = User.objects.count()
    active_this_week = LoginRecord.objects.filter(
        logged_in_at__date__gte=week_ago
    ).values("user").distinct().count()

    # Total data
    total_words = Word.objects.count()
    total_word_banks = WordBank.objects.count()
    total_articles = Article.objects.count()

    # Mastered words
    total_mastered = UserWordStatus.objects.filter(status=WordStatus.MASTERED).count()
    total_learning = UserWordStatus.objects.filter(status=WordStatus.LEARNING).count()
    total_review = UserWordStatus.objects.filter(status=WordStatus.REVIEW).count()

    # Article generation (last 7 days)
    recent_usage = DailyUsage.objects.filter(date__gte=week_ago).aggregate(
        total=Sum("generation_count")
    )["total"] or 0

    # Per-user stats
    user_stats = []
    for user in User.objects.all():
        articles = Article.objects.filter(user=user).count()
        mastered = UserWordStatus.objects.filter(
            user=user, status=WordStatus.MASTERED
        ).count()
        learning = UserWordStatus.objects.filter(
            user=user, status=WordStatus.LEARNING
        ).count()
        last_login = LoginRecord.objects.filter(user=user).first()
        total_generations = DailyUsage.objects.filter(
            user=user
        ).aggregate(s=Sum("generation_count"))["s"] or 0
        quiz_count = Quiz.objects.filter(
            article__user=user, is_skipped=False, score__isnull=False
        ).count()
        avg_score = Quiz.objects.filter(
            article__user=user, is_skipped=False, score__isnull=False
        ).aggregate(avg=Sum("score") * 1.0 / Count("id"))["avg"] if quiz_count > 0 else 0

        user_stats.append({
            "username": user.username,
            "is_superuser": user.is_superuser,
            "articles": articles,
            "mastered": mastered,
            "learning": learning,
            "generations": total_generations,
            "quizzes": quiz_count,
            "avg_score": round(avg_score, 1),
            "last_login": last_login.logged_in_at if last_login else None,
        })

    # Recent logins
    recent_logins = LoginRecord.objects.select_related("user").order_by("-logged_in_at")[:20]

    # Word banks overview
    word_banks = []
    for bank in WordBank.objects.all():
        word_banks.append({
            "name": bank.name,
            "word_count": bank.words.count(),
            "created_at": bank.created_at,
        })

    context = {
        "title": "System Dashboard",
        "db_size_mb": round(db_size_mb, 2),
        "db_path": db_path,
        "total_users": total_users,
        "active_this_week": active_this_week,
        "total_words": total_words,
        "total_word_banks": total_word_banks,
        "total_articles": total_articles,
        "total_mastered": total_mastered,
        "total_learning": total_learning,
        "total_review": total_review,
        "recent_usage": recent_usage,
        "user_stats": user_stats,
        "recent_logins": recent_logins,
        "word_banks": word_banks,
    }
    return render(request, "admin/dashboard.html", context)


def backup_view(request):
    """Create and download a database backup."""
    db_path = settings.DATABASES["default"]["NAME"]
    if not os.path.exists(db_path):
        messages.error(request, "Database file not found.")
        return redirect("dashboard:dashboard")

    # Create backup
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"bdc_backup_{timestamp}.sqlite3"

    response = HttpResponse(
        open(db_path, "rb").read(),
        content_type="application/octet-stream",
    )
    response["Content-Disposition"] = f'attachment; filename="{backup_name}"'
    return response


@login_required
def user_management_view(request):
    """User management page (superuser only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("learning:index")

    users = User.objects.all().order_by("username")
    user_data = []
    for u in users:
        profile = u.profile
        user_data.append({
            "id": u.id,
            "username": u.username,
            "is_active": u.is_active,
            "nickname": profile.nickname,
            "daily_limit": profile.daily_limit,
            "global_limit": get_config("limits.daily_generation_limit", 3),
        })

    context = {
        "title": "User Management",
        "user_data": user_data,
    }
    return render(request, "admin/user_management.html", context)


@login_required
def user_edit_view(request, user_id):
    """Edit user: username, password, suspension, daily limit."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("learning:index")

    if request.method == "POST":
        action = request.POST.get("action", "")

        # create_user doesn't need an existing user
        if action == "create_user":
            new_name = request.POST.get("username", "").strip()
            new_pass = request.POST.get("password", "")
            if not new_name:
                messages.error(request, "Username is required.")
            elif User.objects.filter(username=new_name).exists():
                messages.error(request, f"User '{new_name}' already exists.")
            elif len(new_pass) < 4:
                messages.error(request, "Password must be at least 4 characters.")
            else:
                User.objects.create_user(new_name, password=new_pass)
                messages.success(request, f"User '{new_name}' created.")
            return redirect("dashboard:user_management")

    target = get_object_or_404(User, id=user_id)
    profile = target.profile

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "toggle_active":
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            status = "activated" if target.is_active else "suspended"
            messages.success(request, f"User '{target.username}' {status}.")

        elif action == "change_username":
            new_name = request.POST.get("username", "").strip()
            if new_name and new_name != target.username:
                if User.objects.filter(username=new_name).exists():
                    messages.error(request, f"Username '{new_name}' already taken.")
                else:
                    old = target.username
                    target.username = new_name
                    target.save(update_fields=["username"])
                    messages.success(request, f"Username changed: {old} → {new_name}")

        elif action == "change_password":
            new_pass = request.POST.get("password", "")
            if len(new_pass) >= 4:
                target.set_password(new_pass)
                target.save(update_fields=["password"])
                messages.success(request, f"Password changed for '{target.username}'.")
            else:
                messages.error(request, "Password must be at least 4 characters.")

        elif action == "set_limit":
            limit_str = request.POST.get("daily_limit", "-1")
            try:
                limit_val = int(limit_str)
                profile.daily_limit = limit_val
                profile.save(update_fields=["daily_limit"])
                label = str(limit_val) if limit_val >= 0 else "global default"
                messages.success(request, f"Daily limit for '{target.username}' set to {label}.")
            except ValueError:
                messages.error(request, "Invalid limit value.")

    return redirect("dashboard:user_management")


@login_required
def api_config_view(request):
    """DeepSeek API configuration page (superuser only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("learning:index")

    import json

    config_path = Path(__file__).resolve().parent.parent / "config" / "app_config.json"

    if request.method == "POST":
        # Read existing config
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)

        # Update deepseek section
        cfg.setdefault("deepseek", {})
        cfg["deepseek"]["api_key"] = request.POST.get("api_key", "").strip()
        cfg["deepseek"]["base_url"] = request.POST.get("base_url", "").strip()
        cfg["deepseek"]["model"] = request.POST.get("model", "").strip()
        try:
            cfg["deepseek"]["timeout_seconds"] = int(request.POST.get("timeout_seconds", "120"))
        except ValueError:
            cfg["deepseek"]["timeout_seconds"] = 120

        # Write back
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Purge the cached config so next get_config() reads fresh values
        from utils.config import load_config
        load_config.cache_clear()

        messages.success(request, "DeepSeek API configuration updated. Restart recommended for all changes to take effect.")

    # Load current config for display
    ds = get_config("deepseek", {})
    context = {
        "title": "DeepSeek API Configuration",
        "api_key": ds.get("api_key", ""),
        "base_url": ds.get("base_url", "https://api.deepseek.com"),
        "model": ds.get("model", "deepseek-chat"),
        "timeout_seconds": ds.get("timeout_seconds", 120),
    }
    return render(request, "admin/api_config.html", context)


def get_urls():
    """Return custom admin URLs."""
    return [
        path("dashboard/", dashboard_view, name="dashboard"),
        path("backup/", backup_view, name="backup"),
        path("users/", user_management_view, name="user_management"),
        path("users/<int:user_id>/edit/", user_edit_view, name="user_edit"),
        path("api-config/", api_config_view, name="api_config"),
    ]
