from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0010_videotrimrequest"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WowzaApplication",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_index=True, max_length=80, unique=True)),
                ("schedule_id", models.CharField(db_index=True, max_length=80)),
                ("app_type", models.CharField(default="Live", max_length=40)),
                ("storage_dir", models.CharField(blank=True, max_length=255)),
                ("publish_username", models.CharField(blank=True, max_length=80)),
                ("publish_password", models.CharField(blank=True, max_length=128)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("add_date", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("update_date", models.DateTimeField(auto_now=True)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="wowza_applications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-add_date", "name"],
                "indexes": [
                    models.Index(fields=["-add_date", "name"], name="files_wowza_add_dat_857175_idx"),
                    models.Index(fields=["is_active", "-add_date"], name="files_wowza_is_acti_117e1f_idx"),
                ],
            },
        ),
    ]
