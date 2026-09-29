# Native mobile API

The mobile app uses the existing quiz, library, account and grades APIs with
Bearer authentication. This module supplies the native login transport and
idempotent offline-answer submission. All routes below are under `/api/mobile/`.

| Method and route | Purpose |
| --- | --- |
| `POST auth/guest/` | Create a guest and return access/refresh tokens in JSON. |
| `POST auth/otp/` | Validate the existing email OTP and return JSON tokens, without web cookies. Unproven `guest_id` migration is rejected. |
| `POST auth/refresh/` | Refresh using the existing user-aware token serializer. |
| `POST auth/logout/` | Revoke the authenticated user's supplied refresh token. |
| `POST auth/start/` | Create a provider attempt from `provider`, S256 `challenge` and `state`; return its browser URL. |
| `GET auth/browser/<attempt>/` | Bind the attempt to the system browser session and enter existing USOS/Solvro login. |
| `GET auth/complete/` | Return a short-lived, single-use exchange code to `testownik://auth`. |
| `POST auth/exchange/` | Exchange `attempt`, `code` and PKCE `verifier` for tokens. |
| `POST auth/web-session/` | Issue a separate 30-minute access token with `mobile_embed=true` for Wrapped. |
| `POST quizzes/<quiz>/answer/` | Persist an offline answer once and return its receipt. |

Login attempts expire after ten minutes. Once the provider callback issues a
code, it expires after two minutes. Codes are stored as hashes and consumed
atomically. JWTs never travel in provider redirect URLs. The app validates the
returned state before exchange. Guest creation is limited to five per hour;
native login attempts and refresh use the login throttle.

Offline answers contain a UUID `request_id`, `session_id`, quiz `version`,
`question_id`, `selected_answers`, `elapsed_seconds` and nullable `next_question`.
The backend validates ownership, access, the active session and quiz version.
Repeating the same request returns the saved receipt without repeating the
answer or study time; reusing the UUID with a different payload returns 409.
Conflicts preserve local answers for the client to resolve. Receipts remain
valid after a study-session reset.

## Deployment

Use the normal production settings and run `python manage.py migrate` to apply
`mobile_api/0001_initial` before distributing the mobile app. Deploy the
companion web application's `/auth/mobile` bridge at the configured HTTPS web
origin. It must verify JWTs using the same existing signing configuration as
this backend. Provider credentials remain server-side.

The Wrapped token is sent only in an authorization header to the web bridge.
Its generated refresh token is immediately blacklisted; the app's refresh token
is unaffected. The isolated WebView receives an HTTP-only access cookie and no
refresh cookie. Retain HTTPS and existing production cookie/security settings.

## Local verification

`mobile_api.test_settings` is exclusively a disposable integration environment:
SQLite under `/tmp`, captured in-memory email, temporary media and local hosts.
Never use it for deployment or point integration tests at a production database.

```sh
DJANGO_SETTINGS_MODULE=mobile_api.test_settings python manage.py migrate
DJANGO_SETTINGS_MODULE=mobile_api.test_settings python manage.py runserver 127.0.0.1:8765 --noreload
DJANGO_SETTINGS_MODULE=mobile_api.test_settings python manage.py test mobile_api quizzes.tests.test_library_endpoint
```

The mobile frontend's verification record distinguishes automated contract
coverage from native-device, real-provider and release checks. Local tests do
not send real email, invoke paid AI or establish provider credentials or store
signing readiness.
