"""Core learning models: Interest, UserWordStatus, Article, Quiz, DailyUsage, LearningActivity."""

from django.contrib.auth.models import User
from django.db import models

from utils.constants import WordStatus


class Interest(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserWordStatus(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="word_statuses"
    )
    word = models.ForeignKey("wordbank.Word", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=16, choices=WordStatus.choices, default=WordStatus.NEW
    )
    occurrence_count = models.IntegerField(default=0)
    mastered_count = models.IntegerField(default=0)
    mastered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "word")
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} / {self.word.word}: {self.status}"


class Article(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="articles"
    )
    word_bank = models.ForeignKey(
        "wordbank.WordBank", on_delete=models.SET_NULL, null=True
    )
    title = models.CharField(max_length=256)
    content = models.TextField()
    content_html = models.TextField()
    target_word_ids = models.JSONField()
    mastered_word_ids = models.JSONField(default=list)
    hit_word_ids = models.JSONField()
    interests = models.ManyToManyField(Interest, blank=True)
    sentence_complexity = models.IntegerField()
    generated_at = models.DateTimeField(auto_now_add=True)
    is_regenerated = models.BooleanField(default=False)

    class Meta:
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=["user", "-generated_at"], name="article_user_gen_idx"),
        ]

    def __str__(self):
        return self.title


class Quiz(models.Model):
    article = models.OneToOneField(
        Article, on_delete=models.CASCADE, related_name="quiz"
    )
    questions = models.JSONField()
    user_answers = models.JSONField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    is_skipped = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Quiz for: {self.article.title}"


class DailyUsage(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="daily_usages"
    )
    date = models.DateField()
    generation_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")

    def __str__(self):
        return f"{self.user.username} / {self.date}: {self.generation_count}"


class LearningActivity(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="activities"
    )
    date = models.DateField()
    articles_read = models.IntegerField(default=0)
    quizzes_completed = models.IntegerField(default=0)
    words_mastered = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")

    def __str__(self):
        return f"{self.user.username} / {self.date}: a={self.articles_read} q={self.quizzes_completed} w={self.words_mastered}"


class AppSetting(models.Model):
    """Global app-wide key-value settings shared by all users (e.g. accent)."""

    key = models.CharField(max_length=64, unique=True)
    value = models.CharField(max_length=255, default="")

    def __str__(self):
        return f"{self.key} = {self.value}"
