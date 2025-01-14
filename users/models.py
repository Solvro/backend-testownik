from datetime import date

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import BooleanField
from usos_api.models import Sex, StaffStatus, StudentStatus


class User(AbstractBaseUser, PermissionsMixin):
    id = models.IntegerField(primary_key=True)
    email = models.EmailField(null=True, blank=True)
    student_number = models.CharField(max_length=6)
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

    access_token = models.CharField(max_length=100, null=True, blank=True)
    access_token_secret = models.CharField(max_length=100, null=True, blank=True)

    is_superuser = BooleanField(default=False)
    is_staff = BooleanField(default=False)

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.student_number})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_active_student_and_not_staff(self):
        return (
            self.student_status is StudentStatus.ACTIVE_STUDENT.value
            and self.staff_status is StaffStatus.NOT_STAFF.value
        )

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
    initial_repetitions = models.IntegerField(default=1)
    wrong_answer_repetitions = models.IntegerField(default=1)

    def __str__(self):
        return f"Settings for {self.user}"


class Term(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    finish_date = models.DateField(null=True, blank=True)

    @property
    def is_current(self):
        return (
            self.start_date <= date.today() <= self.end_date
            if self.start_date and self.end_date
            else None
        )


class StudyGroup(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100)
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
