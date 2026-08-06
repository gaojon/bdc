"""Fetch pronunciation, English definitions, examples, synonyms, and antonyms
from the Free Dictionary API (https://dictionaryapi.dev/).

Usage:
    python manage.py fetch_word_data              # all words
    python manage.py fetch_word_data --bank IELTS  # single bank
    python manage.py fetch_word_data --dry-run     # preview only, no DB writes
    python manage.py fetch_word_data --delay 0.2   # custom delay between requests
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand

from wordbank.models import Word, WordBank, WordBankEntry


API_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en/"
USER_AGENT = "BDC-Vocabulary/1.0"


def fetch_word(word_text: str, timeout: int = 8) -> dict | None:
    """Fetch word data from Free Dictionary API. Returns parsed dict or None."""
    encoded = urllib.parse.quote(word_text)
    url = API_BASE + encoded
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode())
    except urllib.error.HTTPError:
        pass
    except Exception:
        pass
    return None


def parse_api_response(data: list) -> dict:
    """Extract fields from API response into a flat dict.

    Returns dict with keys: pronounce, english_definition, examples,
    synonyms, antonyms.  All values are strings.
    """
    result = {
        "pronounce": "",
        "english_definition": "",
        "examples": "",
        "synonyms": "",
        "antonyms": "",
    }

    if not data or not isinstance(data, list):
        return result

    entry = data[0]

    # --- Phonetic ---
    # Prefer the first phonetics entry with a text field
    for ph in entry.get("phonetics", []):
        if ph.get("text"):
            result["pronounce"] = ph["text"].strip("/")
            break
    if not result["pronounce"] and entry.get("phonetic"):
        result["pronounce"] = entry["phonetic"].strip("/")

    # --- Meanings ---
    def_lines = []
    example_lines = []
    syn_set = set()
    ant_set = set()

    for meaning in entry.get("meanings", []):
        pos = meaning.get("partOfSpeech", "")

        for d in meaning.get("definitions", []):
            definition_text = d.get("definition", "").strip()
            if definition_text:
                if pos:
                    def_lines.append(f"({pos}) {definition_text}")
                else:
                    def_lines.append(definition_text)

            example = d.get("example", "").strip()
            if example:
                example_lines.append(example)

        # Collect synonyms/antonyms from meaning level
        for s in meaning.get("synonyms", []):
            if isinstance(s, str) and s.strip():
                syn_set.add(s.strip())
        for a in meaning.get("antonyms", []):
            if isinstance(a, str) and a.strip():
                ant_set.add(a.strip())

    result["english_definition"] = "\n".join(def_lines)
    result["examples"] = "\n".join(example_lines)
    result["synonyms"] = ", ".join(sorted(syn_set))
    result["antonyms"] = ", ".join(sorted(ant_set))

    return result


class Command(BaseCommand):
    help = "Fetch pronunciation, definitions, examples, synonyms, antonyms from Free Dictionary API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bank",
            type=str,
            help="Limit to a specific word bank name (e.g. IELTS, CET4, 上海高考).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.15,
            help="Delay in seconds between API requests (default: 0.15).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and display but do not save to database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch even for words that already have pronounce.",
        )

    def handle(self, *args, **options):
        bank_name = options["bank"]
        delay = options["delay"]
        dry_run = options["dry_run"]
        force = options["force"]

        queryset = Word.objects.all()
        if bank_name:
            queryset = Word.objects.filter(
                bank_entries__word_bank__name=bank_name
            ).distinct()
        if not force:
            queryset = queryset.filter(pronounce="")

        word_list = list(queryset)
        total = len(word_list)
        self.stdout.write(f"Words to fetch: {total}")

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        stats = {"found": 0, "not_found": 0}
        counter = [0]
        lock = threading.Lock()

        def process_word(word):
            idx = 0
            with lock:
                counter[0] += 1
                idx = counter[0]
            data = fetch_word(word.word)
            time.sleep(delay)
            parsed = parse_api_response(data) if data else None

            if parsed:
                with lock:
                    stats["found"] += 1
                if parsed["pronounce"]:
                    self.stdout.write(f"  [{idx}/{total}] {word.word} /{parsed['pronounce']}/")
                else:
                    self.stdout.write(f"  [{idx}/{total}] {word.word} (no phonetic)")
                if not dry_run:
                    word.pronounce = parsed["pronounce"]
                    word.english_definition = parsed["english_definition"]
                    word.examples = parsed["examples"]
                    word.synonyms = parsed["synonyms"]
                    word.antonyms = parsed["antonyms"]
                    word.save(update_fields=[
                        "pronounce", "english_definition", "examples",
                        "synonyms", "antonyms",
                    ])
            else:
                with lock:
                    stats["not_found"] += 1
                self.stdout.write(f"  [{idx}/{total}] {word.word} NOT FOUND")

        workers = 8
        self.stdout.write(f"Using {workers} concurrent workers...")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_word, w) for w in word_list]
            for f in as_completed(futures):
                f.result()

        self.stdout.write()
        self.stdout.write(f"Done. Found: {stats['found']}, Not found: {stats['not_found']}")
