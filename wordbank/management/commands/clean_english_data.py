"""Rewrite english_definition and examples for all words via DeepSeek API.

Each word gets:
- english_definition: ONE simple definition per part of speech, using common
  everyday words (existing verbose definitions are used as reference).
- examples: ONE simple example per part of speech.

Existing values are overwritten. Words with no existing English data get
freshly generated definitions + examples.

Usage:
    python manage.py clean_english_data                # all 8657 words
    python manage.py clean_english_data --bank CET6     # single bank
    python manage.py clean_english_data --limit 20      # first N words only
    python manage.py clean_english_data --dry-run       # preview only
"""

import re
import time

from django.core.management.base import BaseCommand

from learning.ai import get_client, parse_json_response
from utils.config import get_config
from wordbank.models import Word

BATCH_SIZE = 50
MAX_TOKENS = 8192


def build_batch_prompt(words: list) -> str:
    """words: list of Word objects. Include existing english_definition as context."""
    entries = []
    for w in words:
        if w.english_definition:
            entries.append(f"word: {w.word}\nexisting: {w.english_definition}")
        else:
            entries.append(f"word: {w.word}\nexisting: (none)")
    word_block = "\n\n".join(entries)

    return f"""For each word below, provide a clean English dictionary entry.

For "english_definition":
- EXACTLY ONE definition per part of speech — never two lines with the same "(pos)".
- Use common simple everyday words.
- Format each line as "(pos) definition" with pos like (noun)/(verb)/(adjective)/(adverb)...
- Keep only the parts of speech that are COMMON and USEFUL for a learner. The "existing"
  text is a rough reference (may be verbose or wrong) — simplify it and fix errors.
- If a part of speech has several senses, keep only the MOST COMMON and IMPORTANT one.
- DROP obscure, rare, jargon, or slang senses (e.g. "basso continuo", archaic meanings),
  unless they are the word's main everyday meaning.
- If "existing" is (none), write the word's main parts of speech, one simple definition each.

For "examples":
- EXACTLY ONE short simple example per part of speech — the example count must equal the
  definition count, in the same POS order.
- Use simple common words. Examples may be short phrases or sentences.

Rules:
- Multi-word phrases are a single entry.
- Avoid rare words; prefer plain everyday vocabulary.
- NEVER repeat the same word or phrase consecutively.
- Return ONLY a JSON object:

{{
  "words": [
    {{
      "word": "abandon",
      "english_definition": "(verb) to leave someone or something and never go back\\n(noun) freedom from worry or care",
      "examples": "He abandoned his old car.\\nShe sang with abandon."
    }}
  ]
}}

Words:
{word_block}"""


def clean_text(text: str) -> str:
    """Trim and collapse pathological repetition."""
    text = text.strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


POS_RE = re.compile(r"^\(([^)]+)\)\s*(.*)$")


def enforce_one_per_pos(definition: str, examples: str) -> tuple[str, str]:
    """Mechanically guarantee one definition per POS, examples aligned by count.

    Drops duplicate definitions for the same POS (keeping the first, which the
    model orders most-common-first). Truncates examples to match the definition
    count.
    """
    seen, def_lines = set(), []
    for line in definition.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = POS_RE.match(line)
        key = m.group(1).strip().lower() if m else line.lower()
        if key in seen:
            continue
        seen.add(key)
        def_lines.append(line)

    ex_lines = [l.strip() for l in examples.split("\n") if l.strip()]
    if len(ex_lines) > len(def_lines):
        ex_lines = ex_lines[:len(def_lines)]

    return "\n".join(def_lines), "\n".join(ex_lines)


class Command(BaseCommand):
    help = "Rewrite english_definition (one simple def per POS) and examples (one simple example per POS)."

    def add_arguments(self, parser):
        parser.add_argument("--bank", type=str, help="Limit to a specific word bank.")
        parser.add_argument("--limit", type=int, default=0, help="Process at most N words.")
        parser.add_argument("--force", action="store_true",
                            help="Reprocess even words that already have clean data.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only, no DB writes.")

    def _call_api(self, batch: list) -> dict | None:
        client = get_client()
        model = get_config("deepseek.model", "deepseek-v4-flash")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "You are an English dictionary expert. Return ONLY valid JSON. "
                    "Use simple everyday words in definitions and examples."},
                {"role": "user", "content": build_batch_prompt(batch)},
            ],
            temperature=0.2,
            max_tokens=MAX_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return parse_json_response(response.choices[0].message.content)

    def _apply(self, batch: list, dry_run: bool) -> int:
        data = self._call_api(batch)
        if not data or "words" not in data:
            return -1

        word_map = {w["word"].strip().lower(): w for w in data["words"]}
        updated = 0
        for word in batch:
            info = word_map.get(word.word.lower())
            if not info:
                continue
            definition = clean_text(info.get("english_definition") or "")
            examples = clean_text(info.get("examples") or "")
            definition, examples = enforce_one_per_pos(definition, examples)
            if not definition:
                continue
            if dry_run:
                self.stdout.write(f"  [{word.word}]")
                for line in definition.split("\n"):
                    self.stdout.write(f"    def: {line}")
                for line in examples.split("\n") if examples else []:
                    self.stdout.write(f"    ex : {line}")
            else:
                fields = {"english_definition": definition}
                if examples:
                    fields["examples"] = examples
                Word.objects.filter(id=word.id).update(**fields)
            updated += 1
        return updated

    def _process_batch(self, batch: list, dry_run: bool, stats: dict, depth: int = 0):
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

        if len(batch) == 1:
            stats["failed"].append(batch[0].word)
            self.stdout.write(self.style.WARNING(f"{'  '*depth}[1w] {batch[0].word} failed"))
            return

        self.stdout.write(self.style.WARNING(f"{'  '*depth}[{len(batch)}w] parse failed — splitting"))
        mid = len(batch) // 2
        self._process_batch(batch[:mid], dry_run, stats, depth + 1)
        self._process_batch(batch[mid:], dry_run, stats, depth + 1)
        time.sleep(0.5)

    def handle(self, *args, **options):
        bank_name = options["bank"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        queryset = Word.objects.all()
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
                f"Could not process (still failing): {len(stats['failed'])}"
            ))
            for w in stats["failed"]:
                self.stdout.write(f"  - {w}")
