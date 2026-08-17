"""Learning URL configuration."""

from django.urls import path

from learning import views

app_name = "learning"

urlpatterns = [
    path("", views.index, name="index"),
    path("accent/set/", views.set_accent, name="set_accent"),
    path("review/show-chinese/set/", views.set_review_show_chinese, name="set_review_show_chinese"),
    path("generate/", views.generate_article, name="generate"),
    path("article/<int:article_id>/", views.article, name="article"),
    path(
        "article/<int:article_id>/quiz/submit/",
        views.submit_quiz,
        name="submit_quiz",
    ),
    path(
        "article/<int:article_id>/words/",
        views.word_review,
        name="word_review",
    ),
    path(
        "article/<int:article_id>/words/save/",
        views.save_word_decisions,
        name="save_word_decisions",
    ),
    path(
        "article/<int:article_id>/regenerate/",
        views.regenerate,
        name="regenerate",
    ),
    path("history/", views.history, name="history"),
    path(
        "history/<int:article_id>/",
        views.article_detail,
        name="article_detail",
    ),
    path(
        "article/<int:article_id>/delete/",
        views.delete_article,
        name="delete_article",
    ),
    path(
        "articles/delete/",
        views.delete_articles,
        name="delete_articles",
    ),
    path("stats/", views.stats, name="stats"),
]
