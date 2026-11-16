import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import logout
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import timezone
from oauth2_provider.models import AccessToken
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from notifications.utils import send_notification
from quizzes.models import Quiz, QuizSession, SharedQuiz
from quizzes.serializers import AnswerRecordSerializer
from quizzes.services.operations import QuizOperationError, get_readable_quiz, record_quiz_answer
from users.models import AccountType, User
from users.serializers import UserTokenObtainPairSerializer, UserTokenRefreshSerializer
from users.services import delete_account, migrate_guest_to_user
from users.views.email_auth import LoginOtpView

from .models import AnswerReceipt, LoginAttempt


def token_response(user, status=200):
    if user.is_banned or not user.is_active:
        return Response({"detail": "Konto jest niedostępne."}, status=403)
    refresh = UserTokenObtainPairSerializer.get_token(user)
    response = Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=status)
    response["Cache-Control"] = "no-store"
    return response


class LoginThrottle(SimpleRateThrottle):
    scope = "mobile_login"
    rate = "10/min"

    def get_cache_key(self, request, view):
        # Changing from anonymous to a guest bearer must not reset the budget.
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class GuestThrottle(AnonRateThrottle):
    scope = "mobile_guest"
    rate = "5/hour"


class MobileOTPView(LoginOtpView):
    """Reuse the existing OTP validation and rate limits; return tokens without cookies."""

    def post(self, request):
        # Never accept an unproven guest account id for ownership migration.
        if request.data.get("guest_id"):
            return Response({"detail": "guest_id is not supported by mobile login."}, status=400)
        response = super().post(request)
        if response.status_code == 200:
            response.data = {
                "access": response.cookies["access_token"].value,
                "refresh": response.cookies["refresh_token"].value,
            }
            response.cookies.clear()
        response["Cache-Control"] = "no-store"
        return response


class MobileRefreshView(TokenRefreshView):
    serializer_class = UserTokenRefreshSerializer
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class MobileGuestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestThrottle]

    def post(self, request):
        return token_response(User.objects.create_guest_user(), status=201)


class MobileWebSessionView(APIView):
    """Issue a separate, short-lived access token for an isolated embedded browser."""

    def post(self, request):
        if request.user.is_banned or not request.user.is_active:
            return Response(status=403)
        if isinstance(request.auth, AccessToken) and (
            request.auth.application.client_id != "testownik-mobile"
            or not request.auth.allow_scopes(["web:read", "study:read", "quizzes:read", "user:read"])
        ):
            raise PermissionDenied("Embedded sessions require the first-party mobile grant.")
        refresh = UserTokenObtainPairSerializer.get_token(request.user)
        access = refresh.access_token
        refresh.blacklist()  # This browser session must never renew itself independently.
        access.set_exp(lifetime=timedelta(minutes=30))
        access["mobile_embed"] = True
        response = Response({"access": str(access)})
        response["Cache-Control"] = "no-store"
        return response


class MobileLogoutView(APIView):
    def post(self, request):
        try:
            token = RefreshToken(request.data.get("refresh", ""))
            if str(token["user_id"]) != str(request.user.pk):
                return Response(status=403)
            token.blacklist()
        except TokenError:
            pass  # Logging out an expired/revoked session is still successful.
        return Response(status=204)


class StartSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["usos", "solvro"])
    challenge = serializers.RegexField(r"^[A-Za-z0-9_-]{43}$")
    state = serializers.RegexField(r"^[A-Za-z0-9_-]{32,128}$")


class MobileStartView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [JWTAuthentication]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        if request.auth is not None and request.auth.get("mobile_embed"):
            raise PermissionDenied("Embedded sessions are read-only.")
        data = StartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # A guest UUID supplied by a caller is not proof of ownership.
        if request.data.get("guest_id"):
            return Response({"detail": "Use the guest bearer session to keep your quizzes."}, status=400)
        guest = (
            request.user if request.user.is_authenticated and request.user.account_type == AccountType.GUEST else None
        )
        if guest and (guest.is_banned or not guest.is_active):
            return Response(status=403)
        LoginAttempt.objects.filter(expires_at__lt=timezone.now()).delete()
        attempt = LoginAttempt.objects.create(
            **data.validated_data, guest=guest, expires_at=timezone.now() + timedelta(minutes=10)
        )
        return Response({"url": request.build_absolute_uri(f"/api/mobile/auth/browser/{attempt.pk}/")})


def mobile_browser(request, attempt_id):
    attempt = LoginAttempt.objects.filter(pk=attempt_id, expires_at__gt=timezone.now(), consumed=False).first()
    if not attempt or attempt.code_hash:
        return HttpResponseBadRequest("Login expired. Return to the app and try again.")
    # Bind the callback to the browser which actually starts provider authorization.
    request.session["mobile_attempt"] = str(attempt.pk)
    target = "/api/login/usos/" if attempt.provider == "usos" else "/api/login/"
    return redirect(target + "?" + urlencode({"redirect": "/api/mobile/auth/complete/", "confirm_user": "true"}))


@transaction.atomic
def mobile_complete(request):
    attempt_id = request.session.pop("mobile_attempt", None)
    if not attempt_id or not request.user.is_authenticated or request.user.is_banned:
        return HttpResponseBadRequest("Login failed. Return to the app and try again.")
    attempt = (
        LoginAttempt.objects.select_for_update()
        .filter(pk=attempt_id, expires_at__gt=timezone.now(), consumed=False, code_hash="")
        .first()
    )
    if not attempt:
        return HttpResponseBadRequest("Login expired. Return to the app and try again.")
    code = secrets.token_urlsafe(32)
    attempt.user = request.user
    attempt.code_hash = hashlib.sha256(code.encode()).hexdigest()
    attempt.expires_at = timezone.now() + timedelta(minutes=2)
    attempt.save()
    logout(request)
    response = HttpResponse(status=302)
    response["Location"] = "testownik://auth?" + urlencode(
        {"attempt": attempt.pk, "code": code, "state": attempt.state}
    )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


class ExchangeSerializer(serializers.Serializer):
    attempt = serializers.UUIDField()
    code = serializers.CharField(max_length=128)
    verifier = serializers.RegexField(r"^[A-Za-z0-9._~-]{43,128}$")


class MobileExchangeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    @transaction.atomic
    def post(self, request):
        data = ExchangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        attempt = (
            LoginAttempt.objects.select_for_update()
            .filter(pk=values["attempt"], consumed=False, expires_at__gt=timezone.now(), user__isnull=False)
            .first()
        )
        challenge = base64.urlsafe_b64encode(hashlib.sha256(values["verifier"].encode()).digest()).decode().rstrip("=")
        code_hash = hashlib.sha256(values["code"].encode()).hexdigest()
        if (
            not attempt
            or not secrets.compare_digest(challenge, attempt.challenge)
            or not secrets.compare_digest(code_hash, attempt.code_hash)
        ):
            return Response({"detail": "Nieprawidłowy lub wygasły kod logowania."}, status=400)
        if attempt.user.is_banned or not attempt.user.is_active:
            return Response({"detail": "Konto jest niedostępne."}, status=403)
        # Transfer only after both the provider login and native PKCE proof.
        # Keep failed attempts retryable, and lock the guest against concurrent upgrades.
        if attempt.guest_id:
            guest = User.objects.select_for_update().filter(pk=attempt.guest_id).first()
            if guest and not migrate_guest_to_user(str(guest.pk), attempt.user):
                return Response({"detail": "Nie udało się przenieść quizów gościa. Spróbuj ponownie."}, status=409)
        attempt.consumed = True
        attempt.save(update_fields=["consumed"])
        return token_response(attempt.user)


class OfflineAnswerSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    session_id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=0)
    question_id = serializers.UUIDField()
    selected_answers = serializers.ListField(child=serializers.UUIDField(), max_length=100)
    elapsed_seconds = serializers.IntegerField(min_value=0, max_value=3600)
    next_question = serializers.UUIDField(allow_null=True)


class MobileAnswerView(APIView):
    @transaction.atomic
    def post(self, request, quiz_id):
        data = OfflineAnswerSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        # Serialize submissions for this user, including retries from two devices.
        User.objects.select_for_update().get(pk=request.user.pk)
        payload_hash = hashlib.sha256(
            json.dumps({"quiz_id": str(quiz_id), **values}, sort_keys=True, default=str).encode()
        ).hexdigest()
        receipt = AnswerReceipt.objects.filter(user=request.user, request_id=values["request_id"]).first()
        if receipt:
            if receipt.payload_hash != payload_hash:
                return Response({"detail": "Identyfikator odpowiedzi został już użyty."}, status=409)
            return Response(receipt.response)
        try:
            quiz = get_readable_quiz(request.user, quiz_id)
            session = (
                QuizSession.objects.select_for_update()
                .filter(pk=values["session_id"], user=request.user, quiz=quiz, is_active=True)
                .first()
            )
            if session is None or quiz.version != values["version"]:
                return Response(
                    {
                        "detail": (
                            "Quiz lub sesja zmieniły się na innym urządzeniu. Odpowiedzi pozostają zapisane lokalnie."
                        )
                    },
                    status=409,
                )
            result = record_quiz_answer(
                request.user,
                quiz.id,
                values["question_id"],
                [str(x) for x in values["selected_answers"]],
                closed_only=True,
                study_time=session.study_time.total_seconds() + values["elapsed_seconds"],
                next_question_id=values["next_question"],
            )
        except QuizOperationError as exc:
            transaction.set_rollback(True)
            return Response({"detail": exc.message}, status=exc.status_code)
        response = json.loads(json.dumps(dict(AnswerRecordSerializer(result.record).data), default=str))
        AnswerReceipt.objects.create(
            user=request.user, request_id=values["request_id"], payload_hash=payload_hash, response=response
        )
        return Response(response, status=201)


class AccountDeletionSerializer(serializers.Serializer):
    transfer_to_user_id = serializers.UUIDField(required=False, allow_null=True)


class MobileAccountDeletionView(APIView):
    """Explain what deleting the account removes, then delete it, optionally keeping the quizzes alive.

    Limited to the first-party mobile grant: a third-party OAuth app with profile access must
    never be able to delete an account.
    """

    def _require_first_party(self, request):
        if isinstance(request.auth, AccessToken) and request.auth.application.client_id != "testownik-mobile":
            raise PermissionDenied("Account deletion requires the Testownik app.")

    def get(self, request):
        self._require_first_party(request)
        user = request.user
        quizzes = Quiz.objects.filter(creator=user)
        shares = SharedQuiz.objects.filter(quiz__in=quizzes)
        month_ago = timezone.now() - timedelta(days=30)
        response = Response(
            {
                "quizzes": quizzes.count(),
                "public_quizzes": quizzes.filter(visibility__gte=2).count(),
                "shared_people": shares.filter(user__isnull=False).exclude(user=user).values("user").distinct().count(),
                "shared_groups": shares.filter(study_group__isnull=False).values("study_group").distinct().count(),
                "recent_learners": QuizSession.objects.filter(quiz__in=quizzes, updated_at__gte=month_ago)
                .exclude(user=user)
                .values("user")
                .distinct()
                .count(),
                "sessions": QuizSession.objects.filter(user=user).count(),
                "ai_conversations": user.ai_chat_conversations.count(),
            }
        )
        response["Cache-Control"] = "no-store"
        return response

    def post(self, request):
        self._require_first_party(request)
        serializer = AccountDeletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        target = None
        target_id = serializer.validated_data.get("transfer_to_user_id")
        if target_id:
            target = User.objects.filter(pk=target_id).select_related("root_folder").first()
            if (
                target is None
                or target.pk == user.pk
                or not target.is_active
                or target.is_banned
                or target.account_type == AccountType.GUEST
                or target.root_folder is None
            ):
                return Response(
                    {"transfer_to_user_id": ["This person cannot receive your quizzes."]},
                    status=400,
                )
        with transaction.atomic():
            moved = 0
            if target is not None:
                moved = Quiz.objects.filter(creator=user).update(creator=target, folder=target.root_folder)
                # Keep a quiz shared with its new owner from also listing them as an invitee.
                SharedQuiz.objects.filter(quiz__creator=target, user=target).delete()
            name = user.full_name or user.email
            delete_account(user)
        if target is not None and moved:
            send_notification(
                target,
                "Otrzymano quizy",
                f"{name} przekazuje Ci swoje quizy ({moved}) przed usunięciem konta. Znajdziesz je w bibliotece.",
                link=f"{settings.FRONTEND_URL}/quizzes",
            )
        return Response(status=204)
