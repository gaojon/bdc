"""Delete articles with zero hit_words (orphaned after DB refactor)."""

from django.core.management.base import BaseCommand
from django.db.models import Q
from learning.models import Article


class Command(BaseCommand):
    help = "Delete articles whose hit_word_ids are empty (orphaned after data migration)."

    def handle(self, *args, **options):
        # Match empty list or null
        old = Article.objects.filter(
            Q(hit_word_ids=[]) | Q(hit_word_ids__isnull=True)
        )
        count = old.count()
        if count == 0:
            self.stdout.write("No empty articles found.")
            return
        self.stdout.write(f"Deleting {count} articles:")
        for a in old:
            self.stdout.write(f"  id={a.id} user={a.user.username} {a.title[:50]}")
        old.delete()
        self.stdout.write(f"Done. Remaining: {Article.objects.count()}")
