"""Tests for word bank browse / batch-master functionality."""

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
