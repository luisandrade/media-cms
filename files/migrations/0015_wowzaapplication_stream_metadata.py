from django.db import migrations, models
import files.models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0014_streamchatban"),
    ]

    operations = [
        migrations.AddField(
            model_name="wowzaapplication",
            name="stream_title",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="wowzaapplication",
            name="poster_image",
            field=models.ImageField(blank=True, max_length=500, null=True, upload_to=files.models.wowza_poster_file_path),
        ),
        migrations.AddField(
            model_name="wowzaapplication",
            name="countdown_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
