"""Admin configuration for learning models."""

from django.contrib import admin

from learning.models import (
    Article,
    DailyUsage,
    Interest,
    LearningActivity,
    Quiz,
    UserWordStatus,
)


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(UserWordStatus)
class UserWordStatusAdmin(admin.ModelAdmin):
    list_display = ("user", "word", "status", "occurrence_count", "review_interval")
    list_filter = ("status",)
    search_fields = ("user__username", "word__word")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "word_bank", "generated_at", "is_regenerated")
    list_filter = ("is_regenerated", "generated_at")
    search_fields = ("title", "user__username")
    readonly_fields = ("generated_at",)


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("article", "score", "is_skipped", "submitted_at")
    list_filter = ("is_skipped",)


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "generation_count")
    list_filter = ("date",)


@admin.register(LearningActivity)
class LearningActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "articles_read", "quizzes_completed", "words_mastered")
    list_filter = ("date",)
