from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = "Create a CampusFlow administrator; prompts securely for a password."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username or len(username) > 80:
            raise CommandError("Username must contain 1-80 characters.")
        password = getpass("Password: ")
        if password != getpass("Confirm password: "):
            raise CommandError("Passwords do not match.")
        if len(password) > 256:
            raise CommandError("Password must contain at most 256 characters.")
        user_model = get_user_model()
        user = user_model(username=username, is_staff=True, is_superuser=True)
        try:
            validate_password(password, user)
            user.full_clean(exclude=["password"])
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        try:
            with transaction.atomic():
                user.set_password(password)
                user.save()
        except IntegrityError as exc:
            raise CommandError("That username already exists.") from exc
        self.stdout.write(self.style.SUCCESS(f"Administrator '{username}' created."))
