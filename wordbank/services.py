"""Wordbank services: CSV import and word management."""

import csv
import io
import logging

from wordbank.models import Word, WordBank, WordBankEntry

logger = logging.getLogger(__name__)


def parse_csv(file_obj, delimiter: str = ",") -> list[dict]:
    """Parse a CSV file and return a list of word data dicts.

    Supports two formats:
    - New: word, pronounce_us, definition (POS embedded in def, e.g. "vt. 放弃 n. 摘要")
    - Old: word, part_of_speech, definition (POS in separate column)

    Args:
        file_obj: A file-like object opened in text mode.
        delimiter: Field separator (default: tab).

    Returns:
        List of dicts with keys: word, part_of_speech, definition, is_phrase.
    """
    words = []
    reader = csv.reader(file_obj, delimiter=delimiter)

    for row_num, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue

        if len(row) < 3:
            logger.warning("Row %d: expected 3 columns, got %d. Skipping.", row_num, len(row))
            continue

        word_text = row[0].strip().lstrip("﻿")
        col2 = row[1].strip()
        col3 = row[2].strip()

        if not word_text:
            logger.warning("Row %d: empty word. Skipping.", row_num)
            continue

        # Detect format: if col2 is a known POS abbreviation, use old format
        known_pos = {"n", "v", "vt", "vi", "a", "adj", "ad", "adv", "prep",
                     "pron", "conj", "interj", "num", "art", "aux"}
        col2_clean = col2.rstrip(".").lower().replace(";", " ").split()

        if col2_clean and all(p in known_pos for p in col2_clean):
            # Old format: col2 is POS, col3 is definition
            pos = col2
            definition = col3
        else:
            # New format: col3 contains "POS. definition POS. definition ..."
            pos = _extract_pos_from_def(col3)
            definition = col3

        pronounce_us = col2 if not (col2_clean and all(p in known_pos for p in col2_clean)) else ""

        is_phrase = " " in word_text

        words.append({
            "word": word_text,
            "pronounce_us": pronounce_us,
            "part_of_speech": pos,
            "definition": definition,
            "is_phrase": is_phrase,
        })

    return words


def _extract_pos_from_def(definition: str) -> str:
    """Extract POS abbreviations from a definition string.

    Parses patterns like:
        "vt. 遗弃；放弃 n. 摘要，提要"  →  "vt; n"
        "a. 抽象的 n. 摘要"            →  "a; n"
    """
    import re
    definition = definition.replace("．", ".")
    pos_markers = re.findall(r"(?:^|\s)([a-z]{1,6})\.\s", definition)
    if pos_markers:
        return "; ".join(pos_markers)
    return ""


def import_words(
    word_bank: WordBank,
    parsed_data: list[dict],
    skip_duplicates: bool = True,
) -> dict:
    """Import words into the shared Word table and link via WordBankEntry.

    Args:
        word_bank: The WordBank to import into.
        parsed_data: List of word dicts from parse_csv().
        skip_duplicates: If True, skip words that already exist in this bank.

    Returns:
        Dict with keys: created (int), skipped (int), errors (list of str).
    """
    created = 0
    skipped = 0
    errors = []

    for entry in parsed_data:
        word_text = entry["word"]

        # Check if already linked to this bank
        if WordBankEntry.objects.filter(
            word_bank=word_bank, word__word=word_text
        ).exists():
            if skip_duplicates:
                skipped += 1
                continue

        try:
            # Get or create the shared Word (dedup across banks)
            word, word_created = Word.objects.get_or_create(
                word=word_text,
                defaults={
                    "pronounce_us": entry.get("pronounce_us", ""),
                    "part_of_speech": entry.get("part_of_speech", ""),
                    "definition": entry.get("definition", ""),
                    "is_phrase": entry.get("is_phrase", False),
                },
            )
            # If word already exists but new import has richer data, update it
            if not word_created and entry.get("definition", "") and len(entry["definition"]) > len(word.definition):
                word.definition = entry["definition"]
                word.part_of_speech = entry.get("part_of_speech", word.part_of_speech)
                word.save(update_fields=["definition", "part_of_speech"])

            # Link word to bank
            WordBankEntry.objects.get_or_create(
                word_bank=word_bank,
                word=word,
            )
            created += 1
        except Exception as e:
            errors.append(f"Failed to import '{word_text}': {e}")

    return {"created": created, "skipped": skipped, "errors": errors}


def import_csv_to_bank(word_bank: WordBank, file_obj) -> dict:
    """Convenience: parse CSV and import into a word bank in one call.

    Returns the same dict as import_words().
    """
    parsed = parse_csv(file_obj)
    return import_words(word_bank, parsed)
