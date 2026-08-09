"""Tests for word bank browse / batch-master functionality."""

import re

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from learning.models import UserWordStatus
from utils.constants import WordStatus
from wordbank.models import Word, WordBank, WordBankEntry


class MasterSelectedWordsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass")
        self.bank = WordBank.objects.create(name="TestBank")
        self.words = [
            Word.objects.create(word=w, part_of_speech="n")
            for w in ["apple", "banana", "cherry"]
        ]
        for w in self.words:
            WordBankEntry.objects.create(word_bank=self.bank, word=w)
        # A word NOT in the bank, used for the security check.
        self.foreign_word = Word.objects.create(word="foreign", part_of_speech="n")

    def test_mark_selected_as_mastered(self):
        c = Client()
        c.force_login(self.user)
        ids = [str(self.words[0].id), str(self.words[1].id)]
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {"word_ids": ids, "letter": "A"},
        )
        self.assertEqual(resp.status_code, 302)
        statuses = {
            ws.word_id: ws.status for ws in UserWordStatus.objects.filter(user=self.user)
        }
        self.assertEqual(statuses[self.words[0].id], WordStatus.MASTERED)
        self.assertEqual(statuses[self.words[1].id], WordStatus.MASTERED)
        self.assertNotIn(self.words[2].id, statuses)  # unselected word untouched
        self.assertIn("letter=A", resp.url)  # redirect preserves the letter

    def test_redirect_preserves_multi_status_filter(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {
                "word_ids": [str(self.words[0].id)],
                "letter": "A",
                "status": ["mastered", "learning"],
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("letter=A", resp.url)
        self.assertIn("status=mastered", resp.url)
        self.assertIn("status=learning", resp.url)

    def test_redirect_preserves_select_all(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {
                "word_ids": [str(self.words[0].id)],
                "letter": "A",
                "select_all": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("select_all=1", resp.url)

    def test_redirect_omits_select_all_when_off(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {"word_ids": [str(self.words[0].id)], "letter": "A"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("select_all", resp.url)

    def test_ignores_words_not_in_bank(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {"word_ids": [str(self.foreign_word.id)]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(UserWordStatus.objects.filter(user=self.user).exists())

    def test_get_redirects_to_manage(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("wordbank:master_selected", args=[self.bank.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("wordbank:manage"))

    def test_mastered_count_caps_at_five(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            reverse("wordbank:master_selected", args=[self.bank.id]),
            {"word_ids": [str(self.words[0].id)]},
        )
        self.assertEqual(resp.status_code, 302)
        ws = UserWordStatus.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(ws.mastered_count, 5)  # direct master skips the review cycle

    def test_checkbox_has_name_for_form_submission(self):
        """A checkbox without a `name` attribute is never submitted, which
        silently broke the batch-master button. Guard against regression."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertEqual(resp.status_code, 200)
        checkbox = re.search(
            r'<input type="checkbox" class="word-check"([^>]*)>', resp.content.decode()
        )
        self.assertIsNotNone(checkbox)
        self.assertRegex(checkbox.group(1), r'\bname="word_ids"')
        self.assertRegex(checkbox.group(1), r'\bform="batch-master-form"')


class EditWordPermissionTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", "b@x.com", "pass")
        self.regular = User.objects.create_user("user1", password="pass")
        self.bank = WordBank.objects.create(name="Bank")
        self.word = Word.objects.create(word="alpha", definition="n. alpha")
        WordBankEntry.objects.create(word_bank=self.bank, word=self.word)

    def test_regular_user_sees_no_edit_button(self):
        c = Client()
        c.force_login(self.regular)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertNotContains(resp, ">Edit</button>")

    def test_admin_sees_edit_button(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertContains(resp, ">Edit</button>")

    def test_regular_user_cannot_edit_via_post(self):
        c = Client()
        c.force_login(self.regular)
        resp = c.post(
            reverse("wordbank:edit_word", args=[self.word.id]),
            {"word": "hacked", "definition": "n. hacked"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("wordbank:manage"))
        self.word.refresh_from_db()
        self.assertEqual(self.word.word, "alpha")  # unchanged
        self.assertEqual(self.word.definition, "n. alpha")

    def test_admin_can_edit_via_post(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.post(
            reverse("wordbank:edit_word", args=[self.word.id]),
            {"word": "alpha2", "definition": "n. beta"},
        )
        self.assertEqual(resp.status_code, 302)
        self.word.refresh_from_db()
        self.assertEqual(self.word.word, "alpha2")


class BrowseStatusFilterTest(TestCase):
    """Status filter (?status=..., repeatable) narrows the current letter by user status."""

    def setUp(self):
        self.user = User.objects.create_user(username="filterer", password="pass")
        self.bank = WordBank.objects.create(name="FilterBank")
        self.mastered_word = Word.objects.create(word="alpha", part_of_speech="n")
        self.learning_word = Word.objects.create(word="actor", part_of_speech="n")
        self.new_word = Word.objects.create(word="angle", part_of_speech="n")
        for w in [self.mastered_word, self.learning_word, self.new_word]:
            WordBankEntry.objects.create(word_bank=self.bank, word=w)
        UserWordStatus.objects.create(
            user=self.user, word=self.mastered_word, status=WordStatus.MASTERED
        )
        UserWordStatus.objects.create(
            user=self.user, word=self.learning_word, status=WordStatus.LEARNING
        )

    def _browse(self, status):
        c = Client()
        c.force_login(self.user)
        return c.get(
            reverse("wordbank:browse", args=[self.bank.id]),
            {"letter": "A", "status": status},
        )

    def test_mastered_filter_shows_only_mastered(self):
        resp = self._browse("mastered")
        self.assertEqual(
            [e["word"] for e in resp.context["entries"]], ["alpha"]
        )

    def test_learning_filter_shows_only_learning(self):
        resp = self._browse("learning")
        self.assertEqual(
            [e["word"] for e in resp.context["entries"]], ["actor"]
        )

    def test_new_filter_shows_only_unrecorded(self):
        resp = self._browse("new")
        self.assertEqual(
            [e["word"] for e in resp.context["entries"]], ["angle"]
        )

    def test_reviewing_alias_maps_to_review(self):
        resp = self._browse("reviewing")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["statuses"], ["review"])

    def test_unknown_status_is_ignored(self):
        """An unknown ?status= value is dropped and the default (all selected)
        applies, so every word is still shown."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(
            reverse("wordbank:browse", args=[self.bank.id]),
            {"letter": "A", "status": "bogus"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["statuses"], ["mastered", "learning", "review", "new"])
        self.assertEqual(len(resp.context["entries"]), 3)

    def test_default_status_is_all_selected(self):
        """Browsing with no ?status= selects every status, i.e. shows all words
        and does not label the list as a filtered subset."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertEqual(resp.context["statuses"], ["mastered", "learning", "review", "new"])
        self.assertFalse(resp.context["filter_active"])
        self.assertEqual(len(resp.context["entries"]), 3)
        # The showing-count span renders empty when every status is selected.
        self.assertRegex(resp.content.decode(), r'id="showing-count">\s*</span>')

    def test_letter_links_preserve_status(self):
        """Alphabet quick-jump hrefs carry the selected statuses so navigating
        letters keeps the filter."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(
            reverse("wordbank:browse", args=[self.bank.id]),
            {"letter": "A", "status": "learning"},
        )
        hrefs = re.findall(r'href="\?letter=([A-Z#])([^"]*)"', resp.content.decode())
        self.assertTrue(hrefs)
        for letter, qs in hrefs:
            self.assertIn("status=learning", qs)

    def test_multiple_statuses_are_unioned(self):
        """?status=mastered&status=learning shows words in either state."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(
            reverse("wordbank:browse", args=[self.bank.id]),
            {"letter": "A", "status": ["mastered", "learning"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["statuses"], ["mastered", "learning"])
        self.assertEqual(
            {e["word"] for e in resp.context["entries"]},
            {"alpha", "actor"},
        )

    def test_partial_returns_results_fragment_only(self):
        """?partial=1 (AJAX status filter) returns the results region, not
        the whole page."""
        c = Client()
        c.force_login(self.user)
        resp = c.get(
            reverse("wordbank:browse", args=[self.bank.id]),
            {"letter": "A", "status": "learning", "partial": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="browse-results"', html)
        self.assertIn('id="showing-count"', html)
        self.assertIn("actor", html)          # the learning word is shown
        self.assertNotIn("alpha", html)       # mastered word filtered out
        self.assertNotIn("<html", html)       # no base template shell


class ImportCsvPermissionTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss3", "b@x.com", "pass")
        self.regular = User.objects.create_user("user3", password="pass")
        self.bank = WordBank.objects.create(name="ImportBank")
        WordBankEntry.objects.create(
            word_bank=self.bank,
            word=Word.objects.create(word="anchor", part_of_speech="n"),
        )

    def test_regular_user_sees_no_import_section(self):
        c = Client()
        c.force_login(self.regular)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertNotContains(resp, "Import CSV")

    def test_admin_sees_import_section(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("wordbank:browse", args=[self.bank.id]), {"letter": "A"})
        self.assertContains(resp, "Import CSV")

    def test_regular_user_cannot_import(self):
        c = Client()
        c.force_login(self.regular)
        resp = c.post(reverse("wordbank:import_csv", args=[self.bank.id]), {})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("wordbank:manage"))
