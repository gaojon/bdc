"""Learning views: article generation, reading, quiz, word review, history, stats."""

import json
import logging
import random
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from learning import ai, services
from learning.models import (
    Article,
    Interest,
    LearningActivity,
    Quiz,
    UserWordStatus,
)
from utils.config import get_config
from utils.constants import (
    SENTENCE_COMPLEXITY_MAX,
    SENTENCE_COMPLEXITY_MIN,
    TARGET_WORDS_DEFAULT,
    TARGET_WORDS_MAX,
    TARGET_WORDS_MIN,
    WordStatus,
)
from wordbank.models import Word, WordBank, WordBankEntry


def _get_version_info() -> dict:
    """Read version.json. Returns dict with version and build_time."""
    path = Path(settings.BASE_DIR) / "version.json"
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "dev", "build_time": ""}


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Index — word bank selection, interests, complexity
# ---------------------------------------------------------------------------


@login_required
def index(request):
    """Home page: select word bank, interests, complexity, and generate articles.

    Also shows article history below the generation form.
    Admin/superuser sees all users' articles; regular users see only their own.
    """
    word_banks = WordBank.objects.all()
    interests = Interest.objects.all()
    profile = request.user.profile

    # Progress summary shown in the BDC heading: mastered = the user's total
    # mastered words (across all banks); un-mastered = words still to learn in
    # the selected bank (辞典), 0 if none is selected. Per-bank counts ride on
    # the <option> elements so the number updates when the dropdown changes.
    mastered_count = UserWordStatus.objects.filter(
        user=request.user, status=WordStatus.MASTERED
    ).count()

    bank_totals = dict(
        WordBankEntry.objects.values("word_bank_id")
        .annotate(n=Count("id"))
        .values_list("word_bank_id", "n")
    )
    bank_mastered = dict(
        UserWordStatus.objects.filter(
            user=request.user, status=WordStatus.MASTERED
        )
        .filter(word__bank_entries__word_bank_id__in=list(bank_totals))
        .values("word__bank_entries__word_bank_id")
        .annotate(n=Count("word_id"))
        .values_list("word__bank_entries__word_bank_id", "n")
    )
    for bank in word_banks:
        bank.unmastered_count = (
            bank_totals.get(bank.id, 0) - bank_mastered.get(bank.id, 0)
        )

    selected_bank_id = profile.selected_word_bank_id
    unmastered_count = 0
    if selected_bank_id:
        unmastered_count = (
            bank_totals.get(selected_bank_id, 0)
            - bank_mastered.get(selected_bank_id, 0)
        )

    # Daily usage info
    allowed, remaining = services.check_daily_limit(request.user)

    # Article history: superuser sees all, regular user sees own
    if request.user.is_superuser:
        articles = Article.objects.select_related("word_bank").prefetch_related("interests", "quiz").order_by("-generated_at")
    else:
        articles = Article.objects.filter(
            user=request.user
        ).select_related("word_bank").prefetch_related("interests", "quiz").order_by("-generated_at")

    # Annotate each article with its interest names (max 2 displayed)
    article_list = []
    for a in articles:
        interest_names = [i.name for i in a.interests.all()]
        article_list.append({
            "id": a.id,
            "title": a.title,
            "word_bank": a.word_bank,
            "generated_at": a.generated_at,
            "hit_word_ids": a.hit_word_ids,
            "is_regenerated": a.is_regenerated,
            "quiz": a.quiz if hasattr(a, "quiz") else None,
            "interest_names": interest_names,
            "interests_display": ", ".join(interest_names[:2]),
            "has_more_interests": len(interest_names) > 2,
            "user": a.user,
        })

    context = {
        "word_banks": word_banks,
        "interests": interests,
        "profile": profile,
        "selected_bank_id": profile.selected_word_bank_id,
        "mastered_count": mastered_count,
        "unmastered_count": unmastered_count,
        "complexity_min": SENTENCE_COMPLEXITY_MIN,
        "complexity_max": SENTENCE_COMPLEXITY_MAX,
        "target_words_min": TARGET_WORDS_MIN,
        "target_words_max": TARGET_WORDS_MAX,
        "target_word_count": profile.target_word_count,
        "article_length": profile.article_length,
        "can_generate": allowed,
        "remaining_generations": remaining,
        "daily_limit": profile.daily_limit if profile.daily_limit >= 0 else get_config("limits.daily_generation_limit", 3),
        "articles": article_list,
    }
    return render(request, "learning/index.html", context)


# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------


@login_required
def set_accent(request):
    """Set the global pronunciation accent (uk/us) for all users.

    Only accepts POST. Redirects back to the referring page.
    """
    if request.method == "POST":
        services.set_accent(request.POST.get("accent", ""))
    return redirect(request.META.get("HTTP_REFERER") or "learning:index")


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------


@login_required
def generate_article(request):
    """Handle article generation POST from index page."""
    if request.method != "POST":
        return redirect("learning:index")

    # Check daily limit
    allowed, remaining = services.check_daily_limit(request.user)
    if not allowed:
        messages.error(request, "Daily generation limit reached. Try again tomorrow.")
        return redirect("learning:index")

    # Parse form data
    word_bank_id = request.POST.get("word_bank_id")
    interest_ids = request.POST.getlist("interest_ids")
    complexity_str = request.POST.get("sentence_complexity", "5")
    # Default article length is driven by config (article.target_word_count)
    default_length = get_config("article.target_word_count", 350)
    article_length_str = request.POST.get("article_length", str(default_length))

    try:
        complexity = int(complexity_str)
        complexity = max(SENTENCE_COMPLEXITY_MIN, min(SENTENCE_COMPLEXITY_MAX, complexity))
    except ValueError:
        complexity = 5

    try:
        article_length = int(article_length_str)
        article_length = max(100, min(600, article_length))
    except ValueError:
        article_length = default_length

    # Number of target vocabulary words fed to the AI (default 30, max 60).
    target_words_str = request.POST.get("target_word_count", str(TARGET_WORDS_DEFAULT))
    try:
        word_count = int(target_words_str)
        word_count = max(TARGET_WORDS_MIN, min(TARGET_WORDS_MAX, word_count))
    except ValueError:
        word_count = TARGET_WORDS_DEFAULT

    word_bank = get_object_or_404(WordBank, id=word_bank_id)
    interests = Interest.objects.filter(id__in=interest_ids) if interest_ids else []

    # Remember the selected word bank for next time
    profile = request.user.profile
    if profile.selected_word_bank_id != word_bank.id:
        # Word-bank switch: keep mastered words, clear learning/review/new
        # tracking so the new bank starts with a clean slate.
        cleared = services.clear_non_mastered_on_bank_switch(request.user)
        messages.info(
            request,
            f"Word bank switched to “{word_bank.name}”. "
            f"Cleared {cleared} learning/review/new record(s); mastered words kept.",
        )
    profile.selected_word_bank_id = word_bank.id
    profile.save(update_fields=["selected_word_bank_id"])

    # Select words for the AI
    selected_words = services.select_words_for_article(
        request.user, word_bank, max_words=word_count
    )
    if not selected_words:
        messages.error(
            request,
            "No words available in this word bank. "
            "All words may be mastered, or the bank is empty.",
        )
        return redirect("learning:index")

    word_strings = [w.word for w in selected_words]
    interest_names = [i.name for i in interests]

    # Update user's preferences
    profile = request.user.profile
    profile.sentence_complexity = complexity
    profile.article_length = article_length
    profile.target_word_count = word_count
    profile.save(
        update_fields=["sentence_complexity", "article_length", "target_word_count"]
    )

    # Call DeepSeek — article generation
    article_data = ai.generate_article(word_strings, interest_names, complexity, article_length)
    if article_data is None:
        messages.error(request, "AI service is currently unavailable. Please try again later.")
        return redirect("learning:index")

    # Resolve hit_words to Word objects in DB (filter by bank via WordBankEntry).
    # The AI pool already excludes mastered words, but the model may still list a
    # few extra words as hit_words — drop any that are mastered so Review Words
    # never shows vocabulary the user already knows.
    hit_word_strings = article_data.get("hit_words", [])
    hit_words = services.filter_mastered_words(
        request.user,
        list(
            Word.objects.filter(
                bank_entries__word_bank=word_bank, word__in=hit_word_strings
            )
        ),
    )

    # Get mastered words to store on the article record
    mastered_word_strings = services.get_mastered_words(request.user, word_bank)

    # Build highlighted HTML (targets = the filtered, un-mastered hit words)
    content_html = services.build_highlighted_html(
        article_data["content"],
        target_words=[w.word for w in hit_words],
    )

    # Save article
    article = Article.objects.create(
        user=request.user,
        word_bank=word_bank,
        title=article_data["title"],
        content=article_data["content"],
        content_html=content_html,
        target_word_ids=[w.id for w in selected_words],
        mastered_word_ids=[
            w.id
            for w in Word.objects.filter(
                bank_entries__word_bank=word_bank, word__in=mastered_word_strings
            )
        ],
        hit_word_ids=[w.id for w in hit_words],
        sentence_complexity=complexity,
    )
    article.interests.set(interests)

    # Record generation
    services.record_generation(request.user)
    services.cleanup_old_articles(request.user)

    # Increment occurrence for hit words
    services.increment_occurrence([w.id for w in hit_words], request.user)

    # Save quiz from combined response
    quiz_data = article_data.get("quiz", {})
    if quiz_data and quiz_data.get("questions"):
        Quiz.objects.create(article=article, questions=quiz_data["questions"])

    services.record_learning_activity(request.user, articles_read=1)

    return redirect("learning:article", article_id=article.id)


# ---------------------------------------------------------------------------
# Article reading + quiz
# ---------------------------------------------------------------------------


def _build_word_glossary(hit_words: list[Word]) -> dict:
    """Map lowercased word text -> display info for article hover tooltips.

    Shows pronunciation (current accent, falling back to the other), POS,
    English/Chinese definitions, examples, and synonyms/antonyms.
    """
    accent = services.get_accent()
    glossary = {}
    for w in hit_words:
        if accent == "uk":
            pron = f"UK /{w.pronounce_uk}/" if w.pronounce_uk else (
                f"US /{w.pronounce_us}/" if w.pronounce_us else ""
            )
        else:
            pron = f"US /{w.pronounce_us}/" if w.pronounce_us else (
                f"UK /{w.pronounce_uk}/" if w.pronounce_uk else ""
            )
        glossary[w.word.lower()] = {
            "word": w.word,
            "pos": w.part_of_speech,
            "pron": pron,
            "definition": w.definition,
            "english_definition": w.english_definition,
            "examples": w.examples,
            "synonyms": w.synonyms,
            "antonyms": w.antonyms,
        }
    return glossary


@login_required
def article(request, article_id):
    """Display article with highlighted words and quiz."""
    if request.user.is_superuser:
        article = get_object_or_404(Article, id=article_id)
    else:
        article = get_object_or_404(Article, id=article_id, user=request.user)

    quiz = None
    if hasattr(article, "quiz"):
        quiz = article.quiz

    # Build glossary from hit words, excluding any the user has since mastered
    hit_words = services.filter_mastered_words(
        request.user, list(Word.objects.filter(id__in=article.hit_word_ids))
    )

    context = {
        "article": article,
        "quiz": quiz,
        "hit_words": hit_words,
        "glossary": _build_word_glossary(hit_words),
        "read_only": request.user != article.user,
    }
    return render(request, "learning/article.html", context)


# ---------------------------------------------------------------------------
# Quiz submission
# ---------------------------------------------------------------------------


@login_required
def submit_quiz(request, article_id):
    """Handle quiz submission."""
    article = get_object_or_404(Article, id=article_id, user=request.user)

    if request.method != "POST":
        return redirect("learning:article", article_id=article_id)

    quiz = get_object_or_404(Quiz, article=article)

    if request.POST.get("skip") == "1":
        quiz.is_skipped = True
        quiz.save(update_fields=["is_skipped"])
        messages.info(request, "Quiz skipped.")
    else:
        user_answers = {}
        correct_count = 0
        questions = quiz.questions

        for q in questions:
            q_id = str(q["id"])
            answer = request.POST.get(f"q_{q_id}")
            user_answers[q_id] = answer
            if answer and answer.upper() == q["correct"].upper():
                correct_count += 1

        quiz.user_answers = user_answers
        quiz.score = correct_count
        quiz.submitted_at = date.today()
        quiz.save()

        services.record_learning_activity(request.user, quizzes_completed=1)
        messages.success(request, f"Quiz score: {correct_count}/{len(questions)}")

    return redirect("learning:article", article_id=article_id)


# ---------------------------------------------------------------------------
# Word review — mark keep learning or mastered
# ---------------------------------------------------------------------------


@login_required
def word_review(request, article_id):
    """Review hit words: mark as keep learning or mastered."""
    article = get_object_or_404(Article, id=article_id, user=request.user)

    hit_words = Word.objects.filter(id__in=article.hit_word_ids)
    word_statuses = UserWordStatus.objects.filter(
        user=request.user,
        word__in=hit_words,
    ).select_related("word")

    # Build a map of word_id -> status
    status_map = {ws.word_id: ws for ws in word_statuses}

    word_info = []
    for word in hit_words:
        ws = status_map.get(word.id)
        word_info.append({
            "word": word,
            "status": ws.status if ws else "new",
            "is_already_mastered": ws.status == WordStatus.MASTERED if ws else False,
        })

    context = {
        "article": article,
        "word_info": word_info,
        "show_chinese": services.get_review_show_chinese(),
    }
    return render(request, "learning/word_review.html", context)


@login_required
def set_review_show_chinese(request):
    """Set whether the review page shows Chinese definitions (whole-page default)."""
    if request.method != "POST":
        return redirect("learning:index")

    value = request.POST.get("show_chinese")
    services.set_review_show_chinese(value == "yes")
    return redirect(request.META.get("HTTP_REFERER") or "learning:index")


@login_required
def save_word_decisions(request, article_id):
    """Save word keep/mastered decisions."""
    article = get_object_or_404(Article, id=article_id, user=request.user)

    if request.method != "POST":
        return redirect("learning:word_review", article_id=article_id)

    action = request.POST.get("action", "")
    mastered_count = 0

    if action == "master_all":
        word_ids = article.hit_word_ids
    else:
        word_ids = request.POST.getlist("master_word_ids")

    if word_ids:
        word_statuses = UserWordStatus.objects.filter(
            user=request.user,
            word_id__in=word_ids,
        )
        # Create missing statuses for words the user hasn't encountered before
        existing_ids = set(ws.word_id for ws in word_statuses)
        new_ids = [int(wid) for wid in word_ids if int(wid) not in existing_ids]
        if new_ids:
            new_statuses = [
                UserWordStatus(user=request.user, word_id=wid, status=WordStatus.LEARNING)
                for wid in new_ids
            ]
            UserWordStatus.objects.bulk_create(new_statuses, ignore_conflicts=True)
            word_statuses = UserWordStatus.objects.filter(
                user=request.user,
                word_id__in=word_ids,
            )

        for ws in word_statuses:
            if ws.status != WordStatus.MASTERED:
                services.mark_word_mastered(ws)
                mastered_count += 1

    services.record_learning_activity(request.user, words_mastered=mastered_count)
    messages.success(request, f"{mastered_count} word(s) marked as mastered.")
    return redirect("learning:index")


# ---------------------------------------------------------------------------
# Recite — listen & match English definitions (TTS dictation)
# ---------------------------------------------------------------------------


def _option_text(word: Word) -> str:
    """English definition preferred, falling back to the stored definition."""
    return (word.english_definition or "").strip() or (word.definition or "").strip()


@login_required
def recite_data(request, article_id):
    """Return the dictation queue: each un-mastered hit word + 4 choices.

    The correct definition is mixed with 3 distractors sampled from the same
    word bank. `correct` holds the index of the right answer in `options`.
    The queue is client-side; only the data (and accent for TTS) is served.
    """
    article = get_object_or_404(Article, id=article_id, user=request.user)
    hit_words = list(Word.objects.filter(id__in=article.hit_word_ids))

    # Drop words the user has already mastered.
    mastered_ids = set(
        UserWordStatus.objects.filter(
            user=request.user,
            word_id__in=[w.id for w in hit_words],
            status=WordStatus.MASTERED,
        ).values_list("word_id", flat=True)
    )
    words = [w for w in hit_words if w.id not in mastered_ids]

    # Candidate distractor definitions from the same word bank.
    bank_pool = []
    if article.word_bank:
        bank_pool = list(
            Word.objects.filter(bank_entries__word_bank=article.word_bank)
            .exclude(id__in=[w.id for w in words])
            .values_list("id", "english_definition", "definition")
        )

    def _distractors(word: Word, n: int) -> list[str]:
        """Sample n distinct distractor definition texts, skipping the answer."""
        answer = _option_text(word)
        chosen = []
        for _, en, cn in bank_pool:
            text = (en or "").strip() or (cn or "").strip()
            if text and text != answer:
                chosen.append(text)
            if len(chosen) >= n:
                break
        return chosen

    accent = services.get_accent()
    queue = []
    for w in words:
        correct = _option_text(w)
        options = [correct] + _distractors(w, 3)
        random.shuffle(options)
        queue.append({
            "id": w.id,
            "word": w.word,
            "pronounce": w.pronounce_us if accent != "uk" else w.pronounce_uk,
            "options": options,
            "correct": options.index(correct),
        })

    return JsonResponse({"accent": accent, "words": queue})


@login_required
def recite_master(request, article_id):
    """Mark a recited word as mastered (POST word_id). Owner only."""
    article = get_object_or_404(Article, id=article_id, user=request.user)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    word_id = request.POST.get("word_id", "")
    if not word_id.isdigit():
        return JsonResponse({"ok": False, "error": "missing word_id"}, status=400)
    word_id = int(word_id)

    if word_id not in article.hit_word_ids:
        return JsonResponse({"ok": False, "error": "word not in article"}, status=400)

    ws, _ = UserWordStatus.objects.get_or_create(
        user=request.user,
        word_id=word_id,
        defaults={"status": WordStatus.LEARNING},
    )
    if ws.status != WordStatus.MASTERED:
        services.mark_word_mastered(ws)
    services.record_learning_activity(request.user, words_mastered=1)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------


@login_required
def regenerate(request, article_id):
    """Regenerate article with same parameters."""
    old_article = get_object_or_404(Article, id=article_id, user=request.user)

    if request.method != "POST":
        return redirect("learning:article", article_id=article_id)

    # Check daily limit
    allowed, remaining = services.check_daily_limit(request.user)
    if not allowed:
        messages.error(request, "Daily generation limit reached.")
        return redirect("learning:article", article_id=article_id)

    # Use same parameters from old article
    word_bank = old_article.word_bank
    interests = list(old_article.interests.all())
    complexity = old_article.sentence_complexity
    profile = request.user.profile
    article_length = profile.article_length
    # Regenerate with the same number of target words the original used.
    word_count = max(1, len(old_article.target_word_ids))

    selected_words = services.select_words_for_article(
        request.user, word_bank, max_words=word_count
    )
    if not selected_words:
        messages.error(request, "No words available.")
        return redirect("learning:article", article_id=article_id)

    word_strings = [w.word for w in selected_words]
    interest_names = [i.name for i in interests]

    article_data = ai.generate_article(word_strings, interest_names, complexity, article_length)
    if article_data is None:
        messages.error(request, "AI service unavailable.")
        return redirect("learning:article", article_id=article_id)

    hit_word_strings = article_data.get("hit_words", [])
    hit_words = services.filter_mastered_words(
        request.user,
        list(
            Word.objects.filter(
                bank_entries__word_bank=word_bank, word__in=hit_word_strings
            )
        ),
    )
    mastered_word_strings = services.get_mastered_words(request.user, word_bank)
    content_html = services.build_highlighted_html(
        article_data["content"],
        target_words=[w.word for w in hit_words],
    )

    new_article = Article.objects.create(
        user=request.user,
        word_bank=word_bank,
        title=article_data["title"],
        content=article_data["content"],
        content_html=content_html,
        target_word_ids=[w.id for w in selected_words],
        mastered_word_ids=[
            w.id
            for w in Word.objects.filter(
                bank_entries__word_bank=word_bank, word__in=mastered_word_strings
            )
        ],
        hit_word_ids=[w.id for w in hit_words],
        sentence_complexity=complexity,
        is_regenerated=True,
    )
    new_article.interests.set(interests)

    services.record_generation(request.user)
    services.cleanup_old_articles(request.user)
    services.increment_occurrence([w.id for w in hit_words], request.user)

    quiz_data = article_data.get("quiz", {})
    if quiz_data and quiz_data.get("questions"):
        Quiz.objects.create(article=new_article, questions=quiz_data["questions"])

    services.record_learning_activity(request.user, articles_read=1)
    return redirect("learning:article", article_id=new_article.id)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@login_required
def history(request):
    """Redirect to index page (history is now integrated there)."""
    return redirect("learning:index")


@login_required
def article_detail(request, article_id):
    """Read-only view of a past article."""
    if request.user.is_superuser:
        article = get_object_or_404(Article, id=article_id)
    else:
        article = get_object_or_404(Article, id=article_id, user=request.user)

    quiz = None
    if hasattr(article, "quiz"):
        quiz = article.quiz

    hit_words = services.filter_mastered_words(
        request.user, list(Word.objects.filter(id__in=article.hit_word_ids))
    )

    context = {
        "article": article,
        "quiz": quiz,
        "hit_words": hit_words,
        "glossary": _build_word_glossary(hit_words),
        "read_only": request.user != article.user,
    }
    return render(request, "learning/article.html", context)


@login_required
def delete_article(request, article_id):
    """Delete a generated article and its quiz.

    Owners can delete their own articles; superusers can delete any. POST only.
    """
    if request.user.is_superuser:
        article = get_object_or_404(Article, id=article_id)
    else:
        article = get_object_or_404(Article, id=article_id, user=request.user)

    if request.method != "POST":
        return redirect("learning:index")

    title = article.title
    article.delete()
    messages.success(request, f"Article “{title}” deleted.")
    return redirect("learning:index")


@login_required
def delete_articles(request):
    """Delete multiple articles (and their quizzes) in one action.

    Accepts POST with repeated `article_ids` values. Owners can only delete
    their own; superusers can delete any. Quizzes cascade with the article.
    """
    if request.method != "POST":
        return redirect("learning:index")

    ids = [int(i) for i in request.POST.getlist("article_ids") if i.isdigit()]
    if not ids:
        messages.info(request, "No articles selected.")
        return redirect("learning:index")

    qs = Article.objects.filter(id__in=ids)
    if not request.user.is_superuser:
        qs = qs.filter(user=request.user)
    count = qs.count()
    qs.delete()

    if count:
        messages.success(request, f"Deleted {count} article(s).")
    else:
        messages.info(request, "No articles found to delete.")
    return redirect("learning:index")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _nice_ceil(value: int) -> int:
    """Round a non-negative max up to a 'nice' axis top (1, 2, 5 × 10^k)."""
    import math
    if value <= 0:
        return 1
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for m in (1, 2, 5, 10):
        if value <= m * base:
            return m * base
    return 10 * base


def _build_single_chart(key, label, values, days, width=560, height=200):
    """Build SVG geometry for a single-series line chart over 30 days."""
    pad_l, pad_r, pad_t, pad_b = 40, 16, 18, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    ymax = _nice_ceil(max(values) if values else 0)

    def x(i): return pad_l + plot_w * i / 29
    def y(v): return pad_t + plot_h * (1 - v / ymax)

    yticks = []
    tick_vals = list(range(ymax + 1)) if ymax < 5 else [round(ymax * i / 4) for i in range(5)]
    for tv in tick_vals:
        yticks.append({"value": tv, "y": f"{y(tv):.1f}"})

    xlabels = [
        {"x": f"{x(i):.1f}", "label": days[i]["label"]}
        for i in (0, 6, 12, 18, 24, 29)
    ]

    return {
        "key": key,
        "label": label,
        "total": sum(values),
        "points": " ".join(f"{x(i):.1f},{y(values[i]):.1f}" for i in range(30)),
        "dots": [
            {"cx": f"{x(i):.1f}", "cy": f"{y(values[i]):.1f}",
             "value": values[i], "date": days[i]["label"]}
            for i in range(30) if values[i] > 0
        ],
        "yticks": yticks,
        "xlabels": xlabels,
        "width": width,
        "height": height,
        "pad_left": pad_l,
        "plot_right": width - pad_r,
    }


@login_required
def stats(request):
    """Learning statistics and 30-day trend charts.

    Each metric gets its own single-series chart over the last 30 days:
      - learning   = words first added to learning that day (created_at)
      - reviewing  = REVIEW-status words last reviewed that day (mastered_at)
      - mastered   = words that reached mastery that day (mastered_at)
      - articles   = articles read that day (LearningActivity.articles_read)
    """
    user = request.user

    # Aggregate stats
    total_learning = UserWordStatus.objects.filter(
        user=user, status=WordStatus.LEARNING
    ).count()
    total_review = UserWordStatus.objects.filter(
        user=user, status=WordStatus.REVIEW
    ).count()
    total_mastered = UserWordStatus.objects.filter(
        user=user, status=WordStatus.MASTERED
    ).count()
    total_articles = Article.objects.filter(user=user).count()

    quizzes = Quiz.objects.filter(article__user=user, is_skipped=False, score__isnull=False)
    total_quizzes = quizzes.count()
    avg_score = (
        quizzes.aggregate(avg=models.Avg("score"))["avg"]
        if total_quizzes > 0
        else 0
    )

    # ---- 30-day per-metric trends ------------------------------------------
    today = date.today()
    from datetime import timedelta
    start_date = today - timedelta(days=29)

    def _buckets(status=None, date_field="created_at"):
        """Count words per day within the window, grouped by a date field."""
        qs = UserWordStatus.objects.filter(
            user=user, **{f"{date_field}__date__gte": start_date}
        )
        if status:
            qs = qs.filter(status=status)
        rows = qs.values(f"{date_field}__date").annotate(n=Count("id"))
        return {r[f"{date_field}__date"]: r["n"] for r in rows}

    learn_map = _buckets(None, "created_at")
    review_map = _buckets(WordStatus.REVIEW, "mastered_at")
    mastered_map = _buckets(WordStatus.MASTERED, "mastered_at")
    articles_map = {
        r["date"]: r["articles_read"] or 0
        for r in LearningActivity.objects.filter(
            user=user, date__gte=start_date
        ).values("date", "articles_read")
    }

    days = []
    for i in range(30):
        d = today - timedelta(days=29 - i)
        days.append({
            "date": d,
            "label": d.strftime("%m-%d"),
            "learning": learn_map.get(d, 0),
            "reviewing": review_map.get(d, 0),
            "mastered": mastered_map.get(d, 0),
            "articles": articles_map.get(d, 0),
        })

    charts = [
        _build_single_chart("learning", "Learning", [d["learning"] for d in days], days),
        _build_single_chart("reviewing", "Reviewing", [d["reviewing"] for d in days], days),
        _build_single_chart("mastered", "Mastered", [d["mastered"] for d in days], days),
        _build_single_chart("articles", "Articles Read", [d["articles"] for d in days], days),
    ]
    has_activity = any(c["total"] for c in charts)

    context = {
        "total_learning": total_learning,
        "total_review": total_review,
        "total_mastered": total_mastered,
        "total_articles": total_articles,
        "total_quizzes": total_quizzes,
        "avg_score": round(avg_score, 1) if avg_score else 0,
        "charts": charts,
        "trend_days": days,
        "has_activity": has_activity,
    }
    return render(request, "learning/stats.html", context)
