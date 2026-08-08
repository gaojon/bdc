"""Wordbank URL configuration."""

from django.urls import path

from wordbank import views

app_name = "wordbank"

urlpatterns = [
    path("", views.manage, name="manage"),
    path("create/", views.create_bank, name="create_bank"),
    path("<int:bank_id>/", views.browse, name="browse"),
    path("<int:bank_id>/import/", views.import_csv, name="import_csv"),
    path("<int:bank_id>/export/", views.export_csv, name="export_csv"),
    path("<int:bank_id>/delete/", views.delete_bank, name="delete_bank"),
    path("word/<int:word_id>/edit/", views.edit_word, name="edit_word"),
    path("word/<int:word_id>/master/", views.master_word, name="master_word"),
    path("word/<int:word_id>/unmaster/", views.unmaster_word, name="unmaster_word"),
    path("word/<int:word_id>/delete/", views.delete_word, name="delete_word"),
]
