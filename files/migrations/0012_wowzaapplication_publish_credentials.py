from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0011_wowzaapplication"),
    ]

    operations = [
        migrations.AddField(
            model_name="wowzaapplication",
            name="publish_username",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="wowzaapplication",
            name="publish_password",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
