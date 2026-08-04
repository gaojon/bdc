"""WordBank and Word models."""

from django.db import models


class WordBank(models.Model):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Word(models.Model):
    word_bank = models.ForeignKey(
        WordBank, on_delete=models.CASCADE, related_name="words"
    )
    word = models.CharField(max_length=255)
    pronounce = models.CharField(max_length=255, blank=True, default='')
    part_of_speech = models.CharField(max_length=64)
    definition = models.TextField(blank=True, default='')
    is_phrase = models.BooleanField(default=False)

    class Meta:
        unique_together = ("word_bank", "word")

    def __str__(self):
        pos = self.part_of_speech or ''
        return f"{self.word} ({pos})" if pos else self.word
