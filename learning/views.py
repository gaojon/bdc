"""Learning views: article generation, reading, quiz, word review, history, stats."""

import json
import logging
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
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
from utils.constants import SENTENCE_COMPLEXITY_MAX, SENTENCE_COMPLEXITY_MIN, WordStatus
from wordbank.models import Word, WordBank


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
        "complexity_min": SENTENCE_COMPLEXITY_MIN,
        "complexity_max": SENTENCE_COMPLEXITY_MAX,
        "article_length": profile.article_length,
        "can_generate": allowed,
        "remaining_generations": remaining,
        "daily_limit": profile.daily_limit if profile.daily_limit >= 0 else get_config("limits.daily_generation_limit", 3),
        "articles": article_list,
    }
    return render(request, "learning/index.html", context)


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
    article_length_str = request.POST.get("article_length", "500")

    try:
        complexity = int(complexity_str)
        complexity = max(SENTENCE_COMPLEXITY_MIN, min(SENTENCE_COMPLEXITY_MAX, complexity))
    except ValueError:
        complexity = 5

    try:
        article_length = int(article_length_str)
        article_length = max(200, min(800, article_length))
    except ValueError:
        article_length = 500

    word_bank = get_object_or_404(WordBank, id=word_bank_id)
    interests = Interest.objects.filter(id__in=interest_ids) if interest_ids else []

    # Remember the selected word bank for next time
    profile = request.user.profile
    profile.selected_word_bank_id = word_bank.id
    profile.save(update_fields=["selected_word_bank_id"])

    # Select words for the AI
    word_statuses = services.select_words_for_article(request.user, word_bank)
    if not word_statuses:
        messages.error(
            request,
            "No words available in this word bank. "
            "All words may be mastered, or the bank is empty.",
        )
        return redirect("learning:index")

    word_strings = [ws.word.word for ws in word_statuses]
    interest_names = [i.name for i in interests]

    # Update user's preferences
    profile = request.user.profile
    profile.sentence_complexity = complexity
    profile.article_length = article_length
    profile.save(update_fields=["sentence_complexity", "article_length"])

    # Call DeepSeek — article generation
    article_data = ai.generate_article(word_strings, interest_names, complexity, article_length)
    if article_data is None:
        messages.error(request, "AI service is currently unavailable. Please try again later.")
        return redirect("learning:index")

    # Resolve hit_words to Word objects in DB
    hit_word_strings = article_data.get("hit_words", [])
    hit_words = Word.objects.filter(word_bank=word_bank, word__in=hit_word_strings)
    hit_word_map = {w.word.lower(): w for w in hit_words}

    # Get mastered words for light highlighting
    mastered_word_strings = services.get_mastered_words(request.user, word_bank)

    # Build highlighted HTML
    content_html = services.build_highlighted_html(
        article_data["content"],
        target_words=hit_word_strings,
        mastered_words=mastered_word_strings,
    )

    # Save article
    article = Article.objects.create(
        user=request.user,
        word_bank=word_bank,
        title=article_data["title"],
        content=article_data["content"],
        content_html=content_html,
        target_word_ids=[ws.word.id for ws in word_statuses],
        mastered_word_ids=[
            w.id
            for w in Word.objects.filter(
                word_bank=word_bank, word__in=mastered_word_strings
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

    # Generate quiz (second API call)
    quiz_data = ai.generate_quiz(article_data["title"], article_data["content"])
    if quiz_data is not None:
        Quiz.objects.create(article=article, questions=quiz_data["questions"])

    services.record_learning_activity(request.user, articles_read=1)

    return redirect("learning:article", article_id=article.id)


# ---------------------------------------------------------------------------
# Article reading + quiz
# ---------------------------------------------------------------------------


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

    # Build glossary from hit words
    hit_words = Word.objects.filter(id__in=article.hit_word_ids)

    # Build mastered words info for the display
    mastered_words_in_article = Word.objects.filter(
        id__in=article.mastered_word_ids
    ) if article.mastered_word_ids else []

    context = {
        "article": article,
        "quiz": quiz,
        "hit_words": hit_words,
        "mastered_words_in_article": mastered_words_in_article,
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
    }
    return render(request, "learning/word_review.html", context)


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

    word_statuses = services.select_words_for_article(request.user, word_bank)
    if not word_statuses:
        messages.error(request, "No words available.")
        return redirect("learning:article", article_id=article_id)

    word_strings = [ws.word.word for ws in word_statuses]
    interest_names = [i.name for i in interests]

    article_data = ai.generate_article(word_strings, interest_names, complexity, article_length)
    if article_data is None:
        messages.error(request, "AI service unavailable.")
        return redirect("learning:article", article_id=article_id)

    hit_word_strings = article_data.get("hit_words", [])
    hit_words = Word.objects.filter(word_bank=word_bank, word__in=hit_word_strings)
    mastered_word_strings = services.get_mastered_words(request.user, word_bank)
    content_html = services.build_highlighted_html(
        article_data["content"],
        target_words=hit_word_strings,
        mastered_words=mastered_word_strings,
    )

    new_article = Article.objects.create(
        user=request.user,
        word_bank=word_bank,
        title=article_data["title"],
        content=article_data["content"],
        content_html=content_html,
        target_word_ids=[ws.word.id for ws in word_statuses],
        mastered_word_ids=[
            w.id
            for w in Word.objects.filter(
                word_bank=word_bank, word__in=mastered_word_strings
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

    quiz_data = ai.generate_quiz(article_data["title"], article_data["content"])
    if quiz_data is not None:
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

    hit_words = Word.objects.filter(id__in=article.hit_word_ids)

    context = {
        "article": article,
        "quiz": quiz,
        "hit_words": hit_words,
        "mastered_words_in_article": [],
        "read_only": request.user != article.user,
    }
    return render(request, "learning/article.html", context)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@login_required
def stats(request):
    """Learning statistics and heatmap."""
    user = request.user

    # Aggregate stats
    total_learning = UserWordStatus.objects.filter(
        user=user, status=WordStatus.LEARNING
    ).count()
    total_new = UserWordStatus.objects.filter(
        user=user, status=WordStatus.NEW
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

    # Heatmap data: last 365 days of activity
    today = date.today()
    from datetime import timedelta
    start_date = today - timedelta(days=365)
    activities = LearningActivity.objects.filter(
        user=user,
        date__gte=start_date,
    ).values("date", "articles_read", "quizzes_completed", "words_mastered")

    activity_map = {}
    for a in activities:
        activity_map[a["date"]] = (
            (a["articles_read"] or 0)
            + (a["quizzes_completed"] or 0)
            + (a["words_mastered"] or 0)
        )

    context = {
        "total_learning": total_learning,
        "total_new": total_new,
        "total_mastered": total_mastered,
        "total_articles": total_articles,
        "total_quizzes": total_quizzes,
        "avg_score": round(avg_score, 1) if avg_score else 0,
        "activity_map": activity_map,
        "today": today,
        "start_date": start_date,
    }
    return render(request, "learning/stats.html", context)
