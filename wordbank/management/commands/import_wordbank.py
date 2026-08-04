"""Management command to import words from CSV into a word bank.

Usage:
    python manage.py import_wordbank --name "上海高考" --csv data/sh_gaokao.csv
    python manage.py import_wordbank --name "CET4" --csv data/cet4.csv --delimiter ","
"""

from django.core.management.base import BaseCommand, CommandError

from wordbank.models import WordBank
from wordbank.services import import_csv_to_bank


class Command(BaseCommand):
    help = "Import words from a CSV file into a word bank."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", required=True, help="Name of the word bank (created if not exists)."
        )
        parser.add_argument(
            "--csv", required=True, help="Path to the CSV file."
        )
        parser.add_argument(
            "--delimiter", default=",", help="CSV delimiter (default: comma)."
        )
        parser.add_argument(
            "--description", default="", help="Optional word bank description."
        )

    def handle(self, **options):
        name = options["name"]
        csv_path = options["csv"]
        delimiter = options["delimiter"]
        description = options.get("description", "")

        # Get or create the word bank
        word_bank, created = WordBank.objects.get_or_create(
            name=name, defaults={"description": description}
        )
        if created:
            self.stdout.write(f"Created new word bank: '{name}'")

        # Import CSV
        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                result = import_csv_to_bank(word_bank, f)
        except UnicodeDecodeError:
            # Try GBK encoding for Chinese content
            with open(csv_path, encoding="gbk") as f:
                result = import_csv_to_bank(word_bank, f)

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {result['created']} created, "
                f"{result['skipped']} skipped."
            )
        )

        if result["errors"]:
            self.stdout.write(self.style.WARNING("Errors:"))
            for err in result["errors"]:
                self.stdout.write(f"  - {err}")
