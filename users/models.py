import random
import uuid
from datetime import date, timedelta
from typing import Optional

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import BooleanField
from django.utils.timezone import now
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from usos_api.models import Sex, StaffStatus, StudentStatus


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(null=True, blank=True)
    student_number = models.CharField(max_length=6)
    usos_id = models.IntegerField(null=True, blank=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(
        max_length=51
    )  # 51 is the maximum length of a last name in polish: "Czartoryski Rostworowski-Mycielski Anderson Scimone"
    sex = models.CharField(
        max_length=1, choices=[(x.value, x.name) for x in Sex], null=True, blank=True
    )
    student_status = models.IntegerField(
        choices=[(x.value, x.name) for x in StudentStatus], null=True, blank=True
    )
    staff_status = models.IntegerField(
        choices=[(x.value, x.name) for x in StaffStatus], null=True, blank=True
    )
    photo_url = models.URLField(null=True, blank=True)
    overriden_photo_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    access_token = models.CharField(max_length=100, null=True, blank=True)
    access_token_secret = models.CharField(max_length=100, null=True, blank=True)

    is_superuser = BooleanField(default=False)
    is_staff = BooleanField(default=False)

    hide_profile = BooleanField(
        default=False,
        help_text="Hide profile from other users in search and leaderboards, user will still be able to be added by student_number",
    )

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.student_number})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_active_student_and_not_staff(self) -> bool:
        return (
            self.student_status is StudentStatus.ACTIVE_STUDENT.value
            and self.staff_status is StaffStatus.NOT_STAFF.value
        )

    @property
    def is_student_and_not_staff(self) -> bool:
        return (
            self.student_status >= StudentStatus.INACTIVE_STUDENT.value
            and self.staff_status is StaffStatus.NOT_STAFF.value
        )

    @property
    def photo(self) -> Optional[str]:
        return self.overriden_photo_url or self.photo_url

    def get_sex(self):
        return Sex(self.sex)

    def get_student_status(self):
        return StudentStatus(self.student_status)

    def get_staff_status(self):
        return StaffStatus(self.staff_status)

    def get_short_name(self):
        return self.first_name


class UserSettings(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="settings", primary_key=True
    )
    sync_progress = models.BooleanField(default=True)

    # quiz settings
    initial_reoccurrences = models.IntegerField(default=1)
    wrong_answer_reoccurrences = models.IntegerField(default=1)

    def __str__(self):
        return f"Settings for {self.user}"


class Term(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    finish_date = models.DateField(null=True, blank=True)

    @property
    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def is_current(self) -> Optional[bool]:
        return (
            self.start_date <= date.today() <= self.finish_date
            if self.start_date and self.finish_date
            else None
        )


class StudyGroup(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=255)
    members = models.ManyToManyField(User, related_name="study_groups")
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="study_groups",
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name


class EmailLoginToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp_code = models.CharField(max_length=6)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    retry_count = models.IntegerField(default=0)  # Track retries

    MAX_RETRIES = 3  # Limit retries per token

    @staticmethod
    def generate_otp():
        return f"{random.randint(100000, 999999)}"

    @staticmethod
    def create_for_user(user):
        otp = EmailLoginToken.generate_otp()
        token = uuid.uuid4()
        expiration_time = now() + timedelta(minutes=10)  # 10 min expiry

        return EmailLoginToken.objects.create(
            user=user,
            otp_code=otp,
            token=token,
            expires_at=expiration_time,
        )

    def is_expired(self) -> bool:
        return now() > self.expires_at

    @property
    def is_locked(self) -> bool:
        return self.retry_count >= self.MAX_RETRIES

    def add_retry(self):
        self.retry_count += 1
        self.save()
