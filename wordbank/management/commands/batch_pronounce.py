"""Generate US and UK IPA pronunciations via DeepSeek API.

Usage:
    python manage.py batch_pronounce              # all words missing US/UK
    python manage.py batch_pronounce --bank IELTS  # single bank
    python manage.py batch_pronounce --force       # redo all (even existing)
    python manage.py batch_pronounce --dry-run     # preview only
"""

import json
import time

from django.core.management.base import BaseCommand

from learning.ai import get_client, parse_json_response
from utils.config import get_config
from wordbank.models import Word, WordBank, WordBankEntry


BATCH_SIZE = 50


def build_batch_prompt(words: list[str]) -> str:
    """Build prompt to get US/UK IPA for a batch of words."""
    word_list = "\n".join(f"{i+1}. {w}" for i, w in enumerate(words))
    return f"""For each of the following {len(words)} English words, provide:
- US (American) pronunciation in IPA notation
- UK (British) pronunciation in IPA notation

Return ONLY a JSON object:
{{
  "words": [
    {{"word": "abandon", "us": "/əˈbændən/", "uk": "/əˈbændən/"}},
    {{"word": "schedule", "us": "/ˈskɛdʒuːl/", "uk": "/ˈʃɛdjuːl/"}}
  ]
}}

Words:
{word_list}"""


class Command(BaseCommand):
    help = "Generate US/UK IPA pronunciations via DeepSeek API."

    def add_arguments(self, parser):
        parser.add_argument("--bank", type=str, help="Limit to a specific word bank.")
        parser.add_argument("--force", action="store_true", help="Re-generate even if US already exists.")
        parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes.")

    def handle(self, *args, **options):
        bank_name = options["bank"]
        force = options["force"]
        dry_run = options["dry_run"]

        queryset = Word.objects.all()
        if bank_name:
            queryset = Word.objects.filter(
                bank_entries__word_bank__name=bank_name
            ).distinct()
        if not force:
            queryset = queryset.filter(pronounce_us="")

        word_list = list(queryset.order_by("word").values_list("word", flat=True))
        total = len(word_list)
        self.stdout.write(f"Words to process: {total}")

        client = get_client()
        model = get_config("deepseek.model", "deepseek-v4-flash")
        batches = [word_list[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

        updated = 0
        failed = 0

        for bi, batch in enumerate(batches):
            self.stdout.write(f"Batch {bi + 1}/{len(batches)} ({len(batch)} words)... ", ending="")

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a pronunciation expert. Return ONLY valid JSON with IPA notation. Use standard IPA symbols."},
                        {"role": "user", "content": build_batch_prompt(batch)},
                    ],
                    temperature=0.2,
                    max_tokens=4096,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                content = response.choices[0].message.content
                data = parse_json_response(content)

                if not data or "words" not in data:
                    self.stdout.write(self.style.WARNING("PARSE FAILED"))
                    failed += len(batch)
                    continue

                # Update DB
                word_map = {w["word"].lower(): w for w in data["words"] if w.get("us") or w.get("uk")}
                batch_updated = 0
                for word_text in batch:
                    info = word_map.get(word_text.lower())
                    if not info:
                        continue
                    us = (info.get("us") or "").strip("/")
                    uk = (info.get("uk") or "").strip("/")
                    if not dry_run and (us or uk):
                        Word.objects.filter(word=word_text).update(
                            pronounce_us=us, pronounce_uk=uk
                        )
                        batch_updated += 1
                    elif us or uk:
                        batch_updated += 1

                updated += batch_updated
                self.stdout.write(self.style.SUCCESS(f"{batch_updated} updated"))
                time.sleep(0.5)  # rate limit

            except Exception as e:
                self.stdout.write(self.style.ERROR(str(e)[:80]))
                failed += len(batch)
                time.sleep(1)

        self.stdout.write()
        self.stdout.write(f"Done. Updated: {updated}, Failed: {failed}")
