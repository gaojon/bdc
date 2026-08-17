# Generated manually: add target_word_count to Profile (default 30).
# Existing rows get the default, matching TARGET_WORDS_DEFAULT.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_alter_profile_article_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="target_word_count",
            field=models.IntegerField(default=30),
        ),
    ]
