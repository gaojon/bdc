"""Tests for learning views: index page progress counts and Review Words."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from learning import services
from learning.ai import build_combined_prompt
from learning.models import Article, UserWordStatus
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


class ReviewWordsMasteredFilteringTest(TestCase):
    """Mastered words never appear in Review Words, at generation or display."""

    def setUp(self):
        self.user = User.objects.create_user(username="reader", password="pass")
        self.bank = WordBank.objects.create(name="Culinary")
        self.words = [
            Word.objects.create(word=w, part_of_speech="n")
            for w in ["effort", "inspire", "appetite", "cuisine"]
        ]
        for w in self.words:
            WordBankEntry.objects.create(word_bank=self.bank, word=w)

    def _make_article(self):
        return Article.objects.create(
            user=self.user,
            word_bank=self.bank,
            title="Test",
            content="body",
            content_html="<p>body</p>",
            target_word_ids=[w.id for w in self.words],
            hit_word_ids=[w.id for w in self.words],
            sentence_complexity=5,
        )

    def test_filter_mastered_words_drops_only_mastered(self):
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        UserWordStatus.objects.create(
            user=self.user, word=self.words[1], status=WordStatus.LEARNING
        )
        kept = services.filter_mastered_words(self.user, list(self.words))
        self.assertNotIn(self.words[0], kept)   # mastered → dropped
        self.assertIn(self.words[1], kept)      # learning → kept
        self.assertIn(self.words[2], kept)      # new → kept

    def test_generation_does_not_store_mastered_hit_words(self):
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        fake_ai = {
            "title": "Test Article",
            "content": "It takes effort and appetite to cook.",
            "hit_words": ["effort", "appetite"],  # effort is mastered
            "glossary": {"effort": "x", "appetite": "y"},
            "quiz": {"questions": []},
        }
        with patch("learning.ai.generate_article", return_value=fake_ai):
            c = Client()
            c.force_login(self.user)
            resp = c.post(
                reverse("learning:generate"),
                {"word_bank_id": self.bank.id, "sentence_complexity": "5"},
            )
        self.assertEqual(resp.status_code, 302)
        article = Article.objects.get(title="Test Article")
        self.assertIn(self.words[2].id, article.hit_word_ids)   # appetite kept
        self.assertNotIn(self.words[0].id, article.hit_word_ids)  # effort dropped

    def test_article_view_excludes_mastered_review_words(self):
        article = self._make_article()
        # Word mastered AFTER the article was generated.
        UserWordStatus.objects.create(
            user=self.user, word=self.words[0], status=WordStatus.MASTERED
        )
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("learning:article", args=[article.id]))
        self.assertEqual(resp.status_code, 200)
        shown = {w.word for w in resp.context["hit_words"]}
        self.assertNotIn("effort", shown)
        self.assertIn("appetite", shown)


class TargetWordCountTest(TestCase):
    """Target Words selection: 80% hit rate in the prompt, max_words wiring."""

    def setUp(self):
        self.user = User.objects.create_user(username="wordpicker", password="pass")
        self.bank = WordBank.objects.create(name="Words")
        self.words = [
            Word.objects.create(word=w, part_of_speech="n")
            for w in ["alpha", "beta", "gamma", "delta"]
        ]
        for w in self.words:
            WordBankEntry.objects.create(word_bank=self.bank, word=w)

    def _fake_ai(self):
        return {
            "title": "Test Article",
            "content": "Alpha beta.",
            "hit_words": ["alpha"],
            "glossary": {"alpha": "x"},
            "quiz": {"questions": []},
        }

    def test_prompt_requests_80_percent_hit_rate(self):
        words = [f"word{i}" for i in range(30)]
        _, user_prompt = build_combined_prompt(["tech"], words, 5, 350)
        self.assertIn("at least 24 of these", user_prompt)

    def test_generate_passes_selected_word_count(self):
        with patch("learning.ai.generate_article", return_value=self._fake_ai()), patch(
            "learning.services.select_words_for_article",
            return_value=self.words,
        ) as mock_sel:
            c = Client()
            c.force_login(self.user)
            resp = c.post(
                reverse("learning:generate"),
                {
                    "word_bank_id": self.bank.id,
                    "sentence_complexity": "5",
                    "target_word_count": "40",
                },
            )
        self.assertEqual(resp.status_code, 302)
        args, kwargs = mock_sel.call_args
        self.assertEqual(args[1], self.bank)
        self.assertEqual(kwargs["max_words"], 40)

    def test_generate_clamps_word_count_to_max(self):
        with patch("learning.ai.generate_article", return_value=self._fake_ai()), patch(
            "learning.services.select_words_for_article",
            return_value=self.words,
        ):
            c = Client()
            c.force_login(self.user)
            c.post(
                reverse("learning:generate"),
                {
                    "word_bank_id": self.bank.id,
                    "sentence_complexity": "5",
                    "target_word_count": "200",
                },
            )
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.target_word_count, 60)


class BulkDeleteArticlesTest(TestCase):
    """Selecting multiple articles and deleting them in one action."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_superuser=True
        )
        self.bank = WordBank.objects.create(name="Words")
        self.owner_articles = [self._make_article(self.owner, i) for i in range(3)]
        self.other_article = self._make_article(self.other, 1)

    def _make_article(self, user, n):
        return Article.objects.create(
            user=user,
            word_bank=self.bank,
            title=f"A{n}",
            content="body",
            content_html="<p>body</p>",
            target_word_ids=[],
            hit_word_ids=[],
            sentence_complexity=5,
        )

    def test_owner_deletes_own_selected_articles(self):
        ids = [self.owner_articles[0].id, self.owner_articles[1].id]
        c = Client()
        c.force_login(self.owner)
        resp = c.post(reverse("learning:delete_articles"), {"article_ids": ids})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Article.objects.filter(user=self.owner).count(), 1)

    def test_superuser_deletes_any_articles(self):
        ids = [self.owner_articles[0].id, self.other_article.id]
        c = Client()
        c.force_login(self.admin)
        c.post(reverse("learning:delete_articles"), {"article_ids": ids})
        self.assertFalse(Article.objects.filter(id__in=ids).exists())

    def test_non_owner_cannot_delete_others(self):
        c = Client()
        c.force_login(self.owner)
        c.post(
            reverse("learning:delete_articles"),
            {"article_ids": [self.other_article.id]},
        )
        self.assertTrue(Article.objects.filter(id=self.other_article.id).exists())

    def test_get_redirects_without_deleting(self):
        c = Client()
        c.force_login(self.owner)
        resp = c.get(reverse("learning:delete_articles"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Article.objects.count(), 4)

    def test_no_ids_is_a_noop(self):
        c = Client()
        c.force_login(self.owner)
        resp = c.post(reverse("learning:delete_articles"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Article.objects.count(), 4)
