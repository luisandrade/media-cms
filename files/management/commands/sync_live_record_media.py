import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from files.methods import sync_live_record_media
from users.models import User


class Command(BaseCommand):
    help = "Register files from media_files/live_record as Media rows"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Owner username for imported media",
        )
        parser.add_argument(
            "--folder",
            default=os.path.join(settings.MEDIA_ROOT, "live_record"),
            help="Folder to scan, defaults to MEDIA_ROOT/live_record",
        )
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Import media as public",
        )
        parser.add_argument(
            "--unreviewed",
            action="store_true",
            help="Import media as not reviewed",
        )

    def handle(self, *args, **options):
        username = options["username"].strip()
        folder = options["folder"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{username}' does not exist") from exc

        result = sync_live_record_media(
            user=user,
            folder=folder,
            publish=options["publish"],
            reviewed=not options["unreviewed"],
        )

        created = result["created"]
        updated = result["updated"]
        skipped = result["skipped"]

        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} media rows"))
        for media in created:
            self.stdout.write(f"  + {media.media_file.name} -> {media.friendly_token}")

        self.stdout.write(self.style.SUCCESS(f"Updated {len(updated)} media rows"))
        for media in updated:
            self.stdout.write(f"  * {media.media_file.name} -> {media.friendly_token}")

        self.stdout.write(f"Skipped {len(skipped)} files")
        for item in skipped:
            self.stdout.write(f"  - {item['path']} ({item['reason']})")