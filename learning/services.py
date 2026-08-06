"""Core learning business logic: word selection, highlighting, spaced repetition."""

import html
import logging
import random
import re
from datetime import date, datetime

from django.contrib.auth.models import User
from django.utils import timezone

from learning.models import (
    Article,
    DailyUsage,
    LearningActivity,
    UserWordStatus,
)
from utils.config import get_config
from utils.constants import SPACED_REPETITION_INTERVALS, WordStatus
from wordbank.models import Word, WordBank, WordBankEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Word selection
# ---------------------------------------------------------------------------


def select_words_for_article(
    user: User, word_bank: WordBank, max_words: int | None = None
) -> list[Word]:
    """Select words for article generation.

    Returns Word objects from the bank that the user hasn't mastered yet.
    No UserWordStatus records are created here — they are created lazily
    when a word actually appears in an article (hit).

    Excludes mastered words. Unseen words are implicitly treated as "new".

    If the pool exceeds max_words, a random sample is taken (D-20).
    """
    if max_words is None:
        max_words = get_config("article.max_word_pool_size", 500)

    # Get all word IDs in this bank (via bridge table)
    bank_word_ids = set(
        WordBankEntry.objects.filter(word_bank=word_bank)
        .values_list("word_id", flat=True)
    )

    if not bank_word_ids:
        return []

    # Find mastered word IDs for this user (only these are excluded)
    mastered_ids = set(
        UserWordStatus.objects.filter(
            user=user,
            word_id__in=bank_word_ids,
            status=WordStatus.MASTERED,
        ).values_list("word_id", flat=True)
    )

    # Pool = all bank words minus mastered
    available_ids = list(bank_word_ids - mastered_ids)

    if len(available_ids) > max_words:
        available_ids = random.sample(available_ids, max_words)

    return list(Word.objects.filter(id__in=available_ids))


def get_mastered_words(user: User, word_bank: WordBank) -> list[str]:
    """Return the list of mastered word strings for a user in a word bank.

    These appear in articles with light highlighting but are NOT in the AI pool.
    Uses WordBankEntry to find words belonging to this bank.
    """
    bank_word_ids = WordBankEntry.objects.filter(
        word_bank=word_bank
    ).values_list("word_id", flat=True)

    return list(
        UserWordStatus.objects.filter(
            user=user,
            word_id__in=bank_word_ids,
            status=WordStatus.MASTERED,
        ).values_list("word__word", flat=True)
    )


# ---------------------------------------------------------------------------
# Highlight rendering
# ---------------------------------------------------------------------------


def build_highlighted_html(
    content: str,
    target_words: list[str],
    mastered_words: list[str],
) -> str:
    """Wrap target and mastered words in HTML tags for visual highlighting.

    Target words:  <strong class="word-target">word</strong>
    Mastered words: <span class="word-mastered">word</span>

    Uses word-boundary matching to avoid substring false positives.
    Target highlighting takes priority over mastered.
    """
    # Combine words into a single list, longest first to avoid partial matches
    # Track which list each word belongs to
    target_set = set(w.lower() for w in target_words)
    mastered_set = set(w.lower() for w in mastered_words) - target_set

    all_words = sorted(
        [(w, "target") for w in target_set] + [(w, "mastered") for w in mastered_set],
        key=lambda x: len(x[0]),
        reverse=True,
    )

    # Escape HTML first (XSS prevention), then split and wrap in <p> tags
    content = html.escape(content)
    paragraphs = content.strip().split("\n\n")
    html_paragraphs = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        processed = _highlight_words_in_text(para, all_words)
        html_paragraphs.append(f"<p>{processed}</p>")

    return "\n".join(html_paragraphs)


def _highlight_words_in_text(text: str, words_with_type: list[tuple[str, str]]) -> str:
    """Apply highlighting to words in a text, longest-match first.

    Uses a token placeholder approach to avoid nested replacements.
    """
    replacements = {}  # placeholder -> replacement HTML

    for word, wtype in words_with_type:
        placeholder = f"__WORD_{len(replacements)}__"
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)

        if wtype == "target":
            replacement = f'<strong class="word-target">{word}</strong>'
        else:
            replacement = f'<span class="word-mastered">{word}</span>'

        text, count = pattern.subn(placeholder, text)
        if count > 0:
            replacements[placeholder] = replacement

    # Restore placeholders with actual HTML
    for placeholder, replacement in replacements.items():
        text = text.replace(placeholder, replacement)

    return text


# ---------------------------------------------------------------------------
# Spaced repetition (SM-2 simplified)
# ---------------------------------------------------------------------------


def schedule_review(word_status: UserWordStatus) -> None:
    """Mark a word as mastered and schedule its first review.

    Initial interval: 1 day (D-09).
    """
    intervals = get_config("spaced_repetition.intervals", SPACED_REPETITION_INTERVALS)
    word_status.status = WordStatus.MASTERED
    word_status.mastered_at = timezone.now()
    word_status.review_interval = intervals[0]
    word_status.next_review_at = word_status.mastered_at + timezone.timedelta(
        days=intervals[0]
    )
    word_status.save()


def get_mastered_texts(user) -> set:
    """Return lowercase word texts mastered by user across ALL banks."""
    return set(
        UserWordStatus.objects
        .filter(user=user, status=WordStatus.MASTERED)
        .values_list("word__word", flat=True)
    )


def advance_review_interval(word_status: UserWordStatus) -> None:
    """Advance a mastered word to the next review interval.

    Progression: 1 → 3 → 7 → 21 → 60 (caps at 60) (D-09).
    """
    intervals = get_config("spaced_repetition.intervals", SPACED_REPETITION_INTERVALS)

    current_interval = word_status.review_interval
    try:
        current_idx = intervals.index(current_interval)
    except ValueError:
        current_idx = 0

    next_idx = min(current_idx + 1, len(intervals) - 1)
    next_interval = intervals[next_idx]

    word_status.review_interval = next_interval
    word_status.next_review_at = timezone.now() + timezone.timedelta(
        days=next_interval
    )
    word_status.last_reviewed_at = timezone.now()
    word_status.save()


def process_due_reviews() -> int:
    """Find mastered words past their review date and move them to review status.

    Designed to be called daily via cron: python manage.py process_reviews

    Returns the number of words moved to review.
    """
    now = timezone.now()
    due = UserWordStatus.objects.filter(
        status=WordStatus.MASTERED,
        next_review_at__lte=now,
    )

    count = 0
    for status in due:
        status.status = WordStatus.REVIEW
        status.save(update_fields=["status"])
        count += 1

    return count


# ---------------------------------------------------------------------------
# Word decision helpers
# ---------------------------------------------------------------------------


def mark_word_mastered(word_status: UserWordStatus) -> None:
    """Mark a single UserWordStatus as mastered."""
    schedule_review(word_status)


def mark_word_learning(word_status: UserWordStatus) -> None:
    """Restore a word to learning status (undo mastered/removed)."""
    word_status.status = WordStatus.LEARNING
    word_status.mastered_at = None
    word_status.review_interval = 0
    word_status.next_review_at = None
    word_status.save()


def batch_master_words(word_statuses: list[UserWordStatus]) -> int:
    """Mark a batch of words as mastered. Returns count mastered."""
    count = 0
    for ws in word_statuses:
        if ws.status != WordStatus.MASTERED:
            schedule_review(ws)
            count += 1
    return count


def increment_occurrence(word_ids: list[int], user: User) -> None:
    """Increment occurrence_count for words that appeared in an article.

    Creates UserWordStatus records lazily for words the user hasn't
    encountered before.
    """
    existing_ids = set(
        UserWordStatus.objects.filter(
            user=user, word_id__in=word_ids
        ).values_list("word_id", flat=True)
    )

    # Create status records for newly encountered words
    new_ids = [wid for wid in word_ids if wid not in existing_ids]
    if new_ids:
        UserWordStatus.objects.bulk_create([
            UserWordStatus(user=user, word_id=wid, status=WordStatus.LEARNING)
            for wid in new_ids
        ], ignore_conflicts=True)

    UserWordStatus.objects.filter(
        user=user,
        word_id__in=word_ids,
    ).update(occurrence_count=models.F("occurrence_count") + 1)


# Need models import for update query
from django.db import models  # noqa: E402


# ---------------------------------------------------------------------------
# Daily limit and cleanup
# ---------------------------------------------------------------------------


def check_daily_limit(user: User) -> tuple[bool, int]:
    """Check if user can generate another article today.

    Uses per-user limit if set (>0), otherwise falls back to global config.
    Returns (allowed: bool, remaining: int).
    """
    profile_limit = getattr(user.profile, 'daily_limit', -1)
    if profile_limit >= 0:
        limit = profile_limit
    else:
        limit = get_config("limits.daily_generation_limit", 3)
    today = date.today()

    usage, _ = DailyUsage.objects.get_or_create(user=user, date=today)
    remaining = max(0, limit - usage.generation_count)
    return remaining > 0, remaining


def record_generation(user: User) -> None:
    """Increment the daily generation counter for the user."""
    today = date.today()
    usage, _ = DailyUsage.objects.get_or_create(user=user, date=today)
    usage.generation_count += 1
    usage.save(update_fields=["generation_count"])


def cleanup_old_articles(user: User, max_articles: int | None = None) -> int:
    """Delete articles exceeding the retention limit (D-46).

    Returns number of articles deleted.
    """
    if max_articles is None:
        max_articles = get_config("limits.article_history_retention", 24)

    articles = Article.objects.filter(user=user).order_by("-generated_at")
    count = articles.count()

    if count > max_articles:
        ids_to_keep = list(articles.values_list("id", flat=True)[:max_articles])
        deleted, _ = Article.objects.filter(user=user).exclude(
            id__in=ids_to_keep
        ).delete()
        return deleted

    return 0


def record_learning_activity(
    user: User,
    articles_read: int = 0,
    quizzes_completed: int = 0,
    words_mastered: int = 0,
) -> None:
    """Upsert today's LearningActivity record."""
    today = date.today()
    activity, _ = LearningActivity.objects.get_or_create(user=user, date=today)
    activity.articles_read += articles_read
    activity.quizzes_completed += quizzes_completed
    activity.words_mastered += words_mastered
    activity.save()
