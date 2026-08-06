"""No longer needed — review is now counter-based (5 × Master → MASTERED)."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "No-op: review processing is now counter-based, not timer-based."

    def handle(self, **options):
        self.stdout.write("Review is counter-based. Nothing to do.")
