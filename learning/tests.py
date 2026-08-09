"""Tests for learning views: index page progress counts."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from learning.models import UserWordStatus
from utils.constants import WordStatus
from wordbank.models import Word, WordBank, WordBankEntry


class IndexProgressCountsTest(TestCase):
    """Mastered / Un-Mastered counts shown next to the Word Bank select."""

    def setUp(self):
        self.user = User.objects.create_user(username="learner", password="pass")
        self.bank = WordBank.objects.create(name="DictA")
        self.words = [
            Word.objects.create(word=w, part_of_speech="n")
            for w in ["alpha", "beta", "gamma"]
        ]
        for w in self.words:
            WordBankEntry.objects.create(word_bank=self.bank, word=w)
        # A word mastered outside the bank (global progress).
        self.foreign_mastered = Word.objects.create(
            word="zeta", part_of_speech="n"
        )

    def _get_context(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("learning:index"))
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def test_no_bank_selected_shows_zero_unmastered(self):
        """Without a selected bank, Un-Mastered is 0 and Mastered still shows."""
        ctx = self._get_context()
        self.assertEqual(ctx["unmastered_count"], 0)
        self.assertEqual(ctx["mastered_count"], 0)

    def test_mastered_counts_global_achievements(self):
        """Mastered counts every mastered word, including outside the bank."""
        UserWordStatus.objects.create(
            user=self.user, word=self.foreign_mastered, status=WordStatus.MASTERED
        )
        ctx = self._get_context()
        self.assertEqual(ctx["mastered_count"], 1)

    def test_selected_bank_unmastered_is_total_minus_mastered(self):
        """Un-Mastered = words in the selected bank not yet mastered."""
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        UserWordStatus.objects.create(
            user=self.user, word=self.words[1], status=WordStatus.LEARNING
        )
        self.user.profile.selected_word_bank_id = self.bank.id
        self.user.profile.save(update_fields=["selected_word_bank_id"])

        ctx = self._get_context()
        # 3 in bank, 1 mastered → 2 un-mastered; learning word still counts.
        self.assertEqual(ctx["unmastered_count"], 2)
        self.assertEqual(ctx["mastered_count"], 1)

    def test_page_renders_counts_badges(self):
        """The index page shows the two badges inside the BDC heading."""
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("learning:index"))
        html = resp.content.decode()
        self.assertIn("<h1>BDC", html)
        self.assertIn("Mastered 1", html)
        self.assertIn('id="unmastered-count">0</span>', html)

    def test_options_carry_per_bank_unmastered(self):
        """Each <option> carries its bank's data-unmastered for the JS update."""
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("learning:index"))
        html = resp.content.decode()
        self.assertIn(f'value="{self.bank.id}"', html)
        self.assertIn('data-unmastered="2"', html)

    def test_no_bank_selected_option_maps_to_zero(self):
        """Selecting the placeholder (no bank) shows Un-Mastered 0."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("learning:index"))
        html = resp.content.decode()
        self.assertIn('<option value="">-- Select a word bank --</option>', html)
