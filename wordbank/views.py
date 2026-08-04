"""Wordbank management views: browse, import, export, edit."""

import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.db.models.functions import Lower

from learning.models import UserWordStatus
from learning.services import get_mastered_texts
from utils.constants import WordStatus
from wordbank.models import Word, WordBank
from wordbank.services import import_csv_to_bank


@login_required
def manage(request):
    """Main word bank management page: list all banks."""
    word_banks = WordBank.objects.all()
    context = {"word_banks": word_banks}
    return render(request, "wordbank/manage.html", context)


@login_required
def browse(request, bank_id):
    """Browse and edit words within a specific word bank."""
    word_bank = get_object_or_404(WordBank, id=bank_id)
    words = word_bank.words.all().order_by(Lower("word"))

    # Get learning status for this user for all words in the bank
    user_statuses = {
        ws.word_id: ws.status
        for ws in UserWordStatus.objects.filter(
            user=request.user,
            word__word_bank=word_bank,
        )
    }

    # Annotate each word with its status, grouped by first letter
    from collections import OrderedDict

    mastered_texts = get_mastered_texts(request.user)

    grouped = OrderedDict()
    for w in words:
        status = user_statuses.get(w.id, "new")
        # Cross-bank: word is mastered if its text is mastered in any bank
        is_mastered = w.word.lower() in mastered_texts or status == WordStatus.MASTERED
        key = w.word[0].upper() if w.word else "#"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append({
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
        "grouped": grouped,
        "letters": list(grouped.keys()),
        "total": sum(len(v) for v in grouped.values()),
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


@login_required
def master_word(request, word_id):
    """Mark a word as mastered directly from the word bank (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word = get_object_or_404(Word, id=word_id)
    bank_id = word.word_bank_id

    ws, _ = UserWordStatus.objects.get_or_create(
        user=request.user,
        word=word,
        defaults={"status": WordStatus.LEARNING},
    )

    from learning.services import schedule_review
    schedule_review(ws)

    messages.success(request, f"Marked as mastered: {word.word}")
    return redirect("wordbank:browse", bank_id=bank_id)


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
    """Export all words in a word bank as a CSV file (Tab-separated)."""
    word_bank = get_object_or_404(WordBank, id=bank_id)
    words = word_bank.words.all().order_by(Lower("word"))

    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = (
        f'attachment; filename="{word_bank.name}.csv"'
    )

    writer = csv.writer(response, delimiter=",", quoting=csv.QUOTE_ALL)
    for word in words:
        writer.writerow([word.word, word.pronounce, word.definition])

    return response


@login_required
def create_bank(request):
    """Create a new word bank (POST only)."""
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
    """Delete a word bank and all its words (POST only)."""
    if request.method != "POST":
        return redirect("wordbank:manage")

    word_bank = get_object_or_404(WordBank, id=bank_id)
    name = word_bank.name
    word_bank.delete()
    messages.success(request, f"Deleted word bank: {name}")
    return redirect("wordbank:manage")
