from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0009_remove_media_is_stream_media_stream"),
    ]

    operations = [
        migrations.CreateModel(
            name="VideoTrimRequest",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("initial", "Initial"), ("running", "Running"), ("success", "Success"), ("fail", "Fail")], default="initial", max_length=20)),
                ("add_date", models.DateTimeField(auto_now_add=True)),
                ("video_action", models.CharField(choices=[("replace", "Replace Original"), ("save_new", "Save as New"), ("create_segments", "Create Segments")], max_length=20)),
                ("media_trim_style", models.CharField(choices=[("no_encoding", "No Encoding"), ("precise", "Precise")], default="no_encoding", max_length=20)),
                ("timestamps", models.JSONField(help_text="Timestamps for trimming")),
                ("media", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="trim_requests", to="files.media")),
            ],
        ),
    ]