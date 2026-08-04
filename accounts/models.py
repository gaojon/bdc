"""Profile model extending Django's built-in User."""

from django.contrib.auth.models import User
from django.db import models

from utils.constants import EnglishLevel, SENTENCE_COMPLEXITY_MAX, SENTENCE_COMPLEXITY_MIN


class LoginRecord(models.Model):
    """Track user login activity."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_records")
    logged_in_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-logged_in_at"]

    def __str__(self):
        return f"{self.user.username} @ {self.logged_in_at}"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    nickname = models.CharField(max_length=64, blank=True)
    english_level = models.CharField(
        max_length=16,
        choices=EnglishLevel.choices,
        default=EnglishLevel.INTERMEDIATE,
    )
    sentence_complexity = models.IntegerField(default=5)
    daily_word_goal = models.IntegerField(default=10)
    selected_word_bank_id = models.IntegerField(null=True, blank=True)
    article_length = models.IntegerField(default=500)  # 200–800
    daily_limit = models.IntegerField(default=-1)  # -1 means use global config

    @property
    def sentence_complexity_display_value(self) -> str:
        return f"{self.sentence_complexity}/{SENTENCE_COMPLEXITY_MAX}"

    def __str__(self):
        return f"{self.user.username}'s profile"
