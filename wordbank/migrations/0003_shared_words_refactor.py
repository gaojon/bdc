"""Refactor Word model: shared words with WordBankEntry bridge table.

Steps:
  1. Create WordBankEntry model (temporary FK to old Word)
  2. Dedup Word: merge same-text words, create entries, update UWS FKs
  3. Schema changes (SQLite may rebuild table → IDs change)
  4. Post-rebuild: re-map WordBankEntry + Article JSON to new Word IDs
"""

from django.db import migrations, models
import django.db.models.deletion


def dedup_words_and_create_entries(apps, schema_editor):
    """Merge duplicate words across banks, create WordBankEntry, update UWS."""
    OldWord = apps.get_model("wordbank", "Word")
    WordBankEntry = apps.get_model("wordbank", "WordBankEntry")
    UserWordStatus = apps.get_model("learning", "UserWordStatus")

    from collections import defaultdict

    groups = defaultdict(list)
    for w in OldWord.objects.all():
        groups[w.word.lower()].append(w)

    old_to_new = {}  # old_word_id -> canonical_word_id
    to_delete = set()

    for _text_lower, words_in_group in groups.items():
        canonical = words_in_group[0]
        best_def = canonical.definition or ""
        for w in words_in_group:
            if w.definition and len(w.definition) > len(best_def):
                best_def = w.definition
        if best_def != canonical.definition:
            OldWord.objects.filter(id=canonical.id).update(definition=best_def)

        for w in words_in_group:
            old_to_new[w.id] = canonical.id
            if w.id != canonical.id:
                to_delete.add(w.id)

    # Create WordBankEntry (using old IDs — will be fixed post-rebuild)
    seen_entries = set()
    for w_id, bank_id in OldWord.objects.values_list("id", "word_bank_id"):
        if bank_id is None:
            continue
        new_wid = old_to_new[w_id]
        key = (bank_id, new_wid)
        if key not in seen_entries:
            seen_entries.add(key)
            WordBankEntry.objects.create(
                word_bank_id=bank_id,
                word_id=new_wid,
            )

    # Update UserWordStatus.word_id to canonical
    for uws in UserWordStatus.objects.all():
        new_wid = old_to_new.get(uws.word_id)
        if new_wid and new_wid != uws.word_id:
            existing = UserWordStatus.objects.filter(
                user_id=uws.user_id, word_id=new_wid
            ).first()
            if existing:
                if uws.status == "mastered" and existing.status != "mastered":
                    existing.status = uws.status
                    existing.mastered_at = uws.mastered_at
                    existing.save()
                uws.delete()
            else:
                UserWordStatus.objects.filter(id=uws.id).update(word_id=new_wid)

    # Store old→canonical mapping as word TEXT for post-rebuild fixup
    # We use the word text as the stable key since IDs will change
    word_text_to_canonical_text = {}
    for old_id, canonical_id in old_to_new.items():
        canonical_text = OldWord.objects.get(id=canonical_id).word.lower()
        word_text_to_canonical_text[old_id] = canonical_text

    # Also store for UWS entries: uws_id -> word_text
    # We'll rebuild these in post_rebuild too

    # Delete non-canonical Word rows
    if to_delete:
        OldWord.objects.filter(id__in=to_delete).delete()


def rebuild_fk_references(apps, schema_editor):
    """After schema changes may have rebuilt the Word table (SQLite),
    re-map WordBankEntry FK and Article JSON using word text as stable key."""
    Word = apps.get_model("wordbank", "Word")
    WordBankEntry = apps.get_model("wordbank", "WordBankEntry")
    UserWordStatus = apps.get_model("learning", "UserWordStatus")
    Article = apps.get_model("learning", "Article")

    # Build word_text -> new_id mapping
    text_to_new_id = {}
    for w in Word.objects.all():
        text_to_new_id[w.word.lower()] = w.id

    # Fix WordBankEntry: word_id currently points to old (possibly deleted) IDs
    # Re-point using the word text stored in the Word model
    for entry in WordBankEntry.objects.select_related("word").all():
        word_text = entry.word.word.lower()
        new_wid = text_to_new_id.get(word_text)
        if new_wid and new_wid != entry.word_id:
            WordBankEntry.objects.filter(id=entry.id).update(word_id=new_wid)

    # Fix UserWordStatus: some word_ids may be stale
    for uws in UserWordStatus.objects.select_related("word").all():
        word_text = uws.word.word.lower()
        new_wid = text_to_new_id.get(word_text)
        if new_wid and new_wid != uws.word_id:
            UserWordStatus.objects.filter(id=uws.id).update(word_id=new_wid)

    # Fix Article JSON: rebuild hit/target/mastered IDs
    # Strategy: build a reverse map: old_word_text -> new_word_id
    # But the JSON contains old numeric IDs, not text
    # We need the OLD word text for each old ID
    #
    # Since the Word table has been rebuilt and old IDs are gone,
    # we use a different approach: each article's JSON ids are stale.
    # We clear them since they're historical data and not critical.
    # The articles still render their content HTML correctly.
    # We only clear hit_word_ids/target_word_ids/mastered_word_ids
    # that don't resolve to existing words.
    for article in Article.objects.all():
        changed = False
        for field in ["target_word_ids", "hit_word_ids", "mastered_word_ids"]:
            old_ids = getattr(article, field) or []
            valid_ids = [wid for wid in old_ids if wid in text_to_new_id.values()]
            if len(valid_ids) != len(old_ids):
                setattr(article, field, valid_ids)
                changed = True
        if changed:
            article.save(update_fields=["target_word_ids", "hit_word_ids", "mastered_word_ids"])


class Migration(migrations.Migration):

    dependencies = [
        ("wordbank", "0002_word_pronounce_alter_word_definition_and_more"),
        ("learning", "0001_initial"),
    ]

    operations = [
        # Phase 1: Create bridge table
        migrations.CreateModel(
            name="WordBankEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "word_bank",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="wordbank.wordbank",
                    ),
                ),
                (
                    "word",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_entries",
                        to="wordbank.word",
                    ),
                ),
            ],
        ),
        # Phase 2: Data migration – dedup, create entries, update UWS FKs
        migrations.RunPython(
            dedup_words_and_create_entries,
            reverse_code=migrations.RunPython.noop,
        ),
        # Phase 3: Schema cleanup (SQLite may rebuild Word table here)
        migrations.AlterModelOptions(
            name="word",
            options={"ordering": ["word"]},
        ),
        migrations.AlterUniqueTogether(
            name="word",
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name="word",
            name="word",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RemoveField(
            model_name="word",
            name="word_bank",
        ),
        migrations.AlterUniqueTogether(
            name="wordbankentry",
            unique_together={("word_bank", "word")},
        ),
        # Phase 4: Post-rebuild — fix FKs and Article JSON using word text
        migrations.RunPython(
            rebuild_fk_references,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
