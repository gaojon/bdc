"""Fill missing pronunciations and Chinese definitions via DeepSeek API.

Generates US/UK IPA, part-of-speech, and Chinese definition in one AI call
per batch, matching the format of existing Word rows. Only fills empty
fields — never overwrites existing data.

Usage:
    python manage.py enrich_words_ai                # all words missing def/IPA
    python manage.py enrich_words_ai --bank CET6     # single bank
    python manage.py enrich_words_ai --limit 30      # first N words only
    python manage.py enrich_words_ai --dry-run       # preview only, no DB writes
    python manage.py enrich_words_ai --force         # also refill words that have data
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from learning.ai import get_client, parse_json_response
from utils.config import get_config
from wordbank.models import Word

BATCH_SIZE = 50
MAX_TOKENS = 8192

# Format examples mirroring existing DB rows, used to steer the AI output.
FORMAT_EXAMPLES = [
    {"word": "abandon", "pronounce_us": "əˈbændən", "pronounce_uk": "əˈbændən",
     "part_of_speech": "vt", "definition": "vt. 丢弃 放弃 抛弃 n. 放纵"},
    {"word": "Africa", "pronounce_us": "ˈæfrɪkə", "pronounce_uk": "ˈæfrɪkə",
     "part_of_speech": "n", "definition": "n. 非洲"},
    {"word": "adapt", "pronounce_us": "əˈdæpt", "pronounce_uk": "əˈdæpt",
     "part_of_speech": "vt; vi", "definition": "vt. 使适应 改编 vi. 适应"},
]


def build_batch_prompt(words: list[str]) -> str:
    """Build prompt asking for IPA + POS + Chinese definition per word."""
    word_list = "\n".join(f"{i+1}. {w}" for i, w in enumerate(words))
    examples = "\n".join(
        f"- {e['word']}: us={e['pronounce_us']}, uk={e['pronounce_uk']}, "
        f"pos={e['part_of_speech']}, def={e['definition']}"
        for e in FORMAT_EXAMPLES
    )
    return f"""For each of the following {len(words)} English words, provide:
- pronounce_us: US IPA notation, WITHOUT surrounding slashes
- pronounce_uk: UK IPA notation, WITHOUT surrounding slashes
- part_of_speech: short POS code (n, a, v, vt, vi, adj, ad, num, pron, prep, conj, int, art, aux, modal); use "; " to separate multiple
- definition: Chinese gloss, format "pos. 释义" with POS embedded; separate multiple meanings by spaces, multiple POS blocks by "; "

Follow these existing format examples:
{examples}

Return ONLY a JSON object:
{{
  "words": [
    {{"word": "abandon", "pronounce_us": "əˈbændən", "pronounce_uk": "əˈbændən", "part_of_speech": "vt", "definition": "vt. 丢弃 放弃 抛弃"}}
  ]
}}

Rules:
- Multi-word phrases are a single dictionary entry.
- If unsure of a pronunciation, give your best standard IPA.
- Each definition must be concise (10-30 Chinese characters).
- NEVER repeat the same word or character consecutively — do not loop.

Words:
{word_list}"""


def clean_definition(text: str) -> str:
    """Collapse pathological repetition (e.g. "bitterly bitterly bitterly ...")."""
    words = text.split()
    out, last, run = [], "", 0
    for w in words:
        if w == last:
            run += 1
            if run >= 4:
                continue  # drop the 5th+ consecutive repeat
        else:
            last, run = w, 1
        out.append(w)
    return " ".join(out).strip()


class Command(BaseCommand):
    help = "Fill missing pronunciations and Chinese definitions via DeepSeek API."

    def add_arguments(self, parser):
        parser.add_argument("--bank", type=str, help="Limit to a specific word bank.")
        parser.add_argument("--limit", type=int, default=0, help="Process at most N words.")
        parser.add_argument("--force", action="store_true",
                            help="Refill even words that already have data.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only, no DB writes.")

    def _call_api(self, batch: list) -> dict | None:
        """One DeepSeek call for a batch. Returns parsed data dict or None."""
        client = get_client()
        model = get_config("deepseek.model", "deepseek-v4-flash")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "You are an English dictionary expert. Return ONLY valid JSON. "
                    "Use standard IPA symbols and concise Chinese glosses."},
                {"role": "user", "content": build_batch_prompt([w.word for w in batch])},
            ],
            temperature=0.2,
            max_tokens=MAX_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return parse_json_response(response.choices[0].message.content)

    def _apply(self, batch: list, dry_run: bool) -> int:
        """Write a successfully-parsed batch to DB. Returns updated count."""
        data = self._call_api(batch)
        if not data or "words" not in data:
            return -1  # parse failure — caller decides retry/split

        word_map = {w["word"].strip().lower(): w for w in data["words"]}
        updated = 0
        for word in batch:
            info = word_map.get(word.word.lower())
            if not info:
                continue
            fields = {}
            us = (info.get("pronounce_us") or "").strip("/").strip()
            uk = (info.get("pronounce_uk") or "").strip("/").strip()
            pos = (info.get("part_of_speech") or "").strip()
            definition = clean_definition((info.get("definition") or "").strip())

            if us and not word.pronounce_us:
                fields["pronounce_us"] = us
            if uk and not word.pronounce_uk:
                fields["pronounce_uk"] = uk
            if pos and not word.part_of_speech:
                fields["part_of_speech"] = pos
            if definition and not word.definition:
                fields["definition"] = definition

            if not fields:
                continue
            if dry_run:
                for k, v in fields.items():
                    self.stdout.write(f"    [{word.word}] {k} = {v[:60]}")
            else:
                Word.objects.filter(id=word.id).update(**fields)
            updated += 1
        return updated

    def _process_batch(self, batch: list, dry_run: bool, stats: dict, depth: int = 0):
        """Process a batch, recursively splitting on parse failure to isolate bad words.

        A single word that still fails after one retry is marked failed and skipped.
        """
        if not batch:
            return
        try:
            n = self._apply(batch, dry_run)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  {'  '*depth}API error: {str(e)[:80]}"))
            n = -1

        if n >= 0:
            stats["updated"] += n
            self.stdout.write(f"{'  '*depth}[{len(batch)}w] {n} updated")
            return

        # Parse failure
        if len(batch) == 1:
            stats["failed"].append(batch[0].word)
            self.stdout.write(self.style.WARNING(f"{'  '*depth}[1w] {batch[0].word} failed"))
            return

        # Split in half and retry recursively to isolate the problem word
        self.stdout.write(self.style.WARNING(f"{'  '*depth}[{len(batch)}w] parse failed — splitting"))
        mid = len(batch) // 2
        self._process_batch(batch[:mid], dry_run, stats, depth + 1)
        self._process_batch(batch[mid:], dry_run, stats, depth + 1)
        time.sleep(0.5)

    def handle(self, *args, **options):
        bank_name = options["bank"]
        limit = options["limit"]
        force = options["force"]
        dry_run = options["dry_run"]

        if force:
            queryset = Word.objects.all()
        else:
            queryset = Word.objects.filter(Q(definition="") | Q(pronounce_us=""))
        if bank_name:
            queryset = queryset.filter(bank_entries__word_bank__name=bank_name).distinct()
        queryset = queryset.order_by("word")
        if limit:
            queryset = queryset[:limit]

        word_list = list(queryset)
        total = len(word_list)
        self.stdout.write(f"Words to process: {total}")

        if not word_list:
            self.stdout.write("Nothing to do.")
            return

        batches = [word_list[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
        stats = {"updated": 0, "failed": []}

        for bi, batch in enumerate(batches):
            self.stdout.write(f"Batch {bi + 1}/{len(batches)} ({len(batch)} words):")
            self._process_batch(batch, dry_run, stats)

        self.stdout.write()
        self.stdout.write(f"Done. Updated: {stats['updated']}")
        if stats["failed"]:
            self.stdout.write(self.style.WARNING(
                f"Could not enrich (still failing): {len(stats['failed'])}"
            ))
            for w in stats["failed"]:
                self.stdout.write(f"  - {w}")
