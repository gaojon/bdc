"""Tests for account views, including CSRF-failure handling.

The persistent production issue: iOS Safari re-submits a stale login form after
a successful login — ``django.contrib.auth.login()`` rotates the CSRF token, so
the still-open form's token is invalid and the re-submit 403s. ``CSRF_FAILURE_VIEW``
is wired to ``accounts.views.csrf_failure``, which turns that dead-end page into a
redirect to a freshly rendered login form.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse


class CsrfFailureRedirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass")
        self.login_path = reverse("accounts:login")

    def test_stale_login_form_redirects_after_successful_login(self):
        """Logging in rotates the CSRF token; re-submitting the stale form with
        the pre-rotation token must redirect to a fresh form, not return 403."""
        c = Client(enforce_csrf_checks=True)
        c.post(
            self.login_path,
            {"username": "tester", "password": "pass"},
        )
        # The form the browser still holds was rendered with the OLD token; the
        # cookie now carries the rotated one → mismatch → CSRF failure.
        resp = c.post(
            self.login_path,
            {
                "username": "tester",
                "password": "pass",
                "csrfmiddlewaretoken": "stale-token-from-before-login",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(self.login_path))

    def test_redirected_form_shows_session_expired_message(self):
        """After the redirect, the fresh login form explains what happened."""
        c = Client(enforce_csrf_checks=True)
        resp = c.post(
            self.login_path,
            {
                "username": "tester",
                "password": "pass",
                "csrfmiddlewaretoken": "stale-token",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Session expired")

    def test_non_login_csrf_failure_redirects_home(self):
        """A stale CSRF token anywhere else redirects to the home page, not 403."""
        c = Client(enforce_csrf_checks=True)
        resp = c.post(
            reverse("accounts:logout"),
            {"csrfmiddlewaretoken": "stale-token"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")

    def test_csrf_failure_redirect_preserves_next(self):
        c = Client(enforce_csrf_checks=True)
        resp = c.post(
            self.login_path + "?next=/learning/",
            {
                "username": "tester",
                "password": "pass",
                "csrfmiddlewaretoken": "stale-token",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(self.login_path + "?next="))

    def test_normal_login_still_works(self):
        c = Client(enforce_csrf_checks=True)
        resp = c.get(self.login_path)
        token = resp.context["csrf_token"]
        resp = c.post(
            self.login_path,
            {
                "username": "tester",
                "password": "pass",
                "csrfmiddlewaretoken": token,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")
