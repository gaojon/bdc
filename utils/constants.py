"""Project-wide constants and enumerations."""

from django.db import models


class WordStatus(models.TextChoices):
    NEW = "new", "New"
    LEARNING = "learning", "Learning"
    REVIEW = "review", "Review"
    MASTERED = "mastered", "Mastered"


class EnglishLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"


SENTENCE_COMPLEXITY_MIN = 1
SENTENCE_COMPLEXITY_MAX = 9

PRESET_INTERESTS = [
    ("technology", "Technology"),
    ("business", "Business"),
    ("sports", "Sports"),
    ("entertainment", "Entertainment"),
    ("science", "Science"),
    ("history", "History"),
    ("travel", "Travel"),
    ("food", "Food"),
    ("health", "Health"),
    ("literature", "Literature"),
    ("scifi", "Sci-Fi"),
    ("mystery", "Mystery & Suspense"),
    ("crime", "Crime & Detective"),
    ("women", "Women"),
    ("peace-love", "Peace & Love"),
    ("relax", "Relaxation"),
    ("gossip", "Gossip"),
]

SPACED_REPETITION_INTERVALS = [1, 3, 7, 21, 60]
