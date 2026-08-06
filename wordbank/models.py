"""WordBank, Word, and WordBankEntry models."""

from django.db import models


class WordBank(models.Model):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Word(models.Model):
    """Shared word entry — one row per unique word text across all banks."""

    word = models.CharField(max_length=255, unique=True)
    pronounce = models.CharField(max_length=255, blank=True, default="")
    pronounce_us = models.CharField(max_length=255, blank=True, default="")
    pronounce_uk = models.CharField(max_length=255, blank=True, default="")
    part_of_speech = models.CharField(max_length=64)
    definition = models.TextField(blank=True, default="")
    is_phrase = models.BooleanField(default=False)

    # Enriched from Free Dictionary API
    english_definition = models.TextField(blank=True, default="")
    examples = models.TextField(blank=True, default="")
    synonyms = models.TextField(blank=True, default="")
    antonyms = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["word"]

    def __str__(self):
        pos = self.part_of_speech or ""
        return f"{self.word} ({pos})" if pos else self.word


class WordBankEntry(models.Model):
    """Bridge table: which words belong to which word bank."""

    word_bank = models.ForeignKey(
        WordBank, on_delete=models.CASCADE, related_name="entries"
    )
    word = models.ForeignKey(
        Word, on_delete=models.CASCADE, related_name="bank_entries"
    )

    class Meta:
        unique_together = ("word_bank", "word")
        verbose_name_plural = "Word bank entries"

    def __str__(self):
        return f"{self.word.word} ∈ {self.word_bank.name}"
