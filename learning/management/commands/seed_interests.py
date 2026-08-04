"""Management command to seed the Interest table with preset categories.

Usage:
    python manage.py seed_interests
"""

from django.core.management.base import BaseCommand

from learning.models import Interest
from utils.constants import PRESET_INTERESTS


class Command(BaseCommand):
    help = "Create preset interest categories."

    def handle(self, **options):
        created = 0
        for slug, name in PRESET_INTERESTS:
            _, was_created = Interest.objects.get_or_create(
                slug=slug, defaults={"name": name}
            )
            if was_created:
                created += 1
                self.stdout.write(f"  Created: {name}")

        if created == 0:
            self.stdout.write("All interests already exist.")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Created {created} interest(s).")
            )
