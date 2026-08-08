"""Wordbank management views: browse, import, export, edit."""

import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.db.models import Count
from django.db.models.functions import Lower, Substr

from learning.models import UserWordStatus
from learning.services import get_mastered_texts
from utils.constants import WordStatus
from wordbank.models import Word, WordBank, WordBankEntry
from wordbank.services import import_csv_to_bank


@login_required
def manage(request):
    """Main word bank management page: list all banks with word counts.

    For the user's currently selected bank, also shows a single set of
    per-user learning stats: reviewing / learning / mastered counts.
    """
    word_banks = list(WordBank.objects.annotate(word_count=Count("entries")))

    selected_bank_id = request.user.profile.selected_word_bank_id
    if selected_bank_id:
        # Pin the selected bank to the leftmost position.
        word_banks.sort(key=lambda b: b.id != selected_bank_id)

    selected_stats = None
    if selected_bank_id:
        status_rows = (
            UserWordStatus.objects.filter(
                user=request.user,
                word__bank_entries__word_bank_id=selected_bank_id,
            )
            .values("status")
            .annotate(n=Count("id"))
        )
        by_status = {row["status"]: row["n"] for row in status_rows}
        selected_stats = {
            "reviewing": by_status.get(WordStatus.REVIEW, 0),
            "learning": by_status.get(WordStatus.LEARNING, 0),
            "mastered": by_status.get(WordStatus.MASTERED, 0),
        }

    context = {
        "word_banks": word_banks,
        "selected_bank_id": selected_bank_id,
        "selected_stats": selected_stats,
    }
    return render(request, "wordbank/manage.html", context)


@login_required
def browse(request, bank_id):
    """Browse and edit words within a specific word bank.

    Only one letter's words are rendered per request so large banks load fast;
    the alphabet bar switches letters via ?letter=.
    """
    word_bank = get_object_or_404(WordBank, id=bank_id)
    words_qs = Word.objects.filter(bank_entries__word_bank=word_bank)

    # Distinct first letters without loading the whole bank (cheap query)
    raw_letters = (
        words_qs.annotate(letter=Substr(Lower("word"), 1, 1))
        .values_list("letter", flat=True)
        .distinct()
    )
    letters = sorted({l.upper() for l in raw_letters if l})
    # Empty-word edge case (normally skipped at import): group under "#"
    if words_qs.filter(word="").exists() and "#" not in letters:
        letters.append("#")

    # Show one letter at a time; default to the first available letter so the
    # page never renders the entire bank.
    letter = (request.GET.get("letter") or "").upper()
    if letter not in letters:
        letter = letters[0] if letters else ""

    if letter == "#":
        letter_words = words_qs.filter(word="")
    elif letter:
        letter_words = words_qs.filter(word__istartswith=letter)
    else:
        letter_words = words_qs.none()

    words = list(letter_words.order_by(Lower("word")))

    # Get learning status for this user for the current letter's words
    user_statuses = {
        ws.word_id: ws.status
        for ws in UserWordStatus.objects.filter(
            user=request.user,
            word_id__in=[w.id for w in words],
        )
    }

    mastered_texts = get_mastered_texts(request.user)

    entries = []
    for w in words:
        status = user_statuses.get(w.id, "new")
        # Cross-bank: word is mastered if its text is mastered in any bank
        is_mastered = w.word.lower() in mastered_texts or status == WordStatus.MASTERED
        entries.append({
            "id": w.id,
            "word": w.word,
            "part_of_speech": w.part_of_speech,
            "definition": w.definition,
            "is_phrase": w.is_phrase,
            "status": status,
            "is_mastered": is_mastered,
        })

    context = {
        "word_bank": word_bank,
        "letters": letters,
        "letter": letter,
        "entries": entries,
        "total": words_qs.count(),
    }
    return render(request, "wordbank/browse.html", context)


@login_required
def edit_word(request, word_id):
    """Edit a single word (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word = get_object_or_404(Word, id=word_id)
    word.word = request.POST.get("word", word.word)
    word.definition = request.POST.get("definition", word.definition)
    word.is_phrase = request.POST.get("is_phrase") == "on"
    # Auto-extract POS from definition
    from wordbank.services import _extract_pos_from_def
    word.part_of_speech = _extract_pos_from_def(word.definition)
    word.save()

    messages.success(request, f"Updated: {word.word}")
    return redirect("wordbank:browse", bank_id=word.word_bank_id)


def _word_browse_redirect(request, word):
    """Return to the word bank browse page the user came from.

    A Word is shared across banks (via WordBankEntry), so redirect back to the
    referer when it points at a browse page; otherwise fall back to the word's
    first bank.
    """
    referer = request.META.get("HTTP_REFERER", "")
    if "/bank/" in referer:
        return redirect(referer)
    bank_id = WordBankEntry.objects.filter(word=word).values_list(
        "word_bank_id", flat=True
    ).first()
    return redirect("wordbank:browse", bank_id=bank_id or 0)


@login_required
def master_word(request, word_id):
    """Mark a word as mastered directly from the word bank (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word = get_object_or_404(Word, id=word_id)

    ws, _ = UserWordStatus.objects.get_or_create(
        user=request.user,
        word=word,
        defaults={"status": WordStatus.LEARNING},
    )

    from learning.services import mark_mastered_direct
    mark_mastered_direct(ws)

    messages.success(request, f"Marked as mastered: {word.word}")
    return _word_browse_redirect(request, word)


@login_required
def unmaster_word(request, word_id):
    """Move a mastered word back to learning (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word = get_object_or_404(Word, id=word_id)

    ws = UserWordStatus.objects.filter(user=request.user, word=word).first()
    if ws is not None:
        from learning.services import unmaster_word as _unmaster
        _unmaster(ws)

    messages.success(request, f"Back to learning: {word.word}")
    return _word_browse_redirect(request, word)


@login_required
def delete_word(request, word_id):
    """Delete a single word (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word = get_object_or_404(Word, id=word_id)
    bank_id = word.word_bank_id
    word_text = word.word
    word.delete()

    messages.success(request, f"Deleted: {word_text}")
    return redirect("wordbank:browse", bank_id=bank_id)


@login_required
def import_csv(request, bank_id):
    """Import words from a CSV file into a word bank."""
    word_bank = get_object_or_404(WordBank, id=bank_id)

    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("wordbank:browse", bank_id=bank_id)

        try:
            file_data = csv_file.read()
            try:
                text = file_data.decode("utf-8")
            except UnicodeDecodeError:
                text = file_data.decode("gbk")

            file_obj = io.StringIO(text)
            result = import_csv_to_bank(word_bank, file_obj)

            messages.success(
                request,
                f"Import complete: {result['created']} created, "
                f"{result['skipped']} skipped.",
            )
            if result["errors"]:
                for err in result["errors"][:5]:
                    messages.warning(request, err)

        except Exception as e:
            messages.error(request, f"Import failed: {e}")

        return redirect("wordbank:browse", bank_id=bank_id)

    return redirect("wordbank:browse", bank_id=bank_id)


@login_required
def export_csv(request, bank_id):
    """Export all words in a word bank as a CSV file (superuser only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("wordbank:manage")
    word_bank = get_object_or_404(WordBank, id=bank_id)
    words = Word.objects.filter(
        bank_entries__word_bank=word_bank
    ).order_by(Lower("word"))

    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = (
        f'attachment; filename="{word_bank.name}.csv"'
    )

    writer = csv.writer(response, delimiter=",", quoting=csv.QUOTE_ALL)
    for word in words:
        writer.writerow([word.word, word.pronounce_us or word.pronounce_uk or "", word.definition])

    return response


@login_required
def create_bank(request):
    """Create a new word bank (superuser only, POST only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("wordbank:manage")
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            WordBank.objects.get_or_create(name=name)
            messages.success(request, f"Created word bank: {name}")
        else:
            messages.error(request, "Name cannot be empty.")
    return redirect("wordbank:manage")


@login_required
def delete_bank(request, bank_id):
    """Delete a word bank and all its words (superuser only, POST only)."""
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect("wordbank:manage")
    if request.method != "POST":
        return redirect("wordbank:manage")

    word_bank = get_object_or_404(WordBank, id=bank_id)
    name = word_bank.name
    word_bank.delete()
    messages.success(request, f"Deleted word bank: {name}")
    return redirect("wordbank:manage")
