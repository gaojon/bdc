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
