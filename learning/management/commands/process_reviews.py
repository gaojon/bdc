"""Management command to process due spaced-repetition reviews.

Designed to run daily via cron:
    0 3 * * * cd /opt/wordlearner && venv/bin/python manage.py process_reviews
"""

from django.core.management.base import BaseCommand

from learning.services import process_due_reviews


class Command(BaseCommand):
    help = "Move mastered words past their review date into review status."

    def handle(self, **options):
        count = process_due_reviews()
        self.stdout.write(
            self.style.SUCCESS(f"Moved {count} word(s) to review status.")
        )
