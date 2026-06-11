from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("files", "0012_wowzaapplication_publish_credentials"),
    ]

    operations = [
        migrations.CreateModel(
            name="StreamChatMessage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField(max_length=500)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("is_pinned", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deleted_stream_chat_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "stream",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_messages",
                        to="files.wowzaapplication",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stream_chat_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [
                    models.Index(fields=["stream", "-created_at"], name="files_strea_stream__c30dcb_idx"),
                    models.Index(fields=["stream", "is_deleted", "-created_at"], name="files_strea_stream__d074bb_idx"),
                ],
            },
        ),
    ]
