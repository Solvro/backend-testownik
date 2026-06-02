# Testownik MCP Server

Testownik exposes an [MCP](https://modelcontextprotocol.io) server so AI agents
can browse quizzes, author quiz content, run study sessions, and read progress on
behalf of a signed-in user.

- **Endpoint:** `https://<host>/api/mcp` (canonical; `/api/mcp/` is also accepted)
- **Transport:** streamable HTTP (stateless)
- **Auth:** OAuth 2.1 (authorization code + PKCE) or a first-party JWT

## Connecting

The server advertises standard discovery documents, so most MCP clients can
connect by pointing at the base URL and completing the OAuth flow:

- `GET /.well-known/oauth-protected-resource` — resource metadata (RFC 9728)
- `GET /.well-known/oauth-authorization-server` — authorization server metadata (RFC 8414)
- Client ID Metadata Document (CIMD), so MCP clients can use an HTTPS metadata
  document URL as their `client_id` without creating one-off registered apps.

The authorization flow uses PKCE (`S256`) and requires the user to approve the
requested scopes on the consent screen. Access tokens expire after 30 minutes;
refresh tokens rotate and last 30 days.

### Client metadata

OAuth clients can publish metadata at an HTTPS URL and use that URL as the
`client_id`. Testownik fetches the metadata, validates the requested redirect URI
against the document, and reuses one internal OAuth application for that metadata
URL.

Example:

```json
{
  "client_id": "https://example.com/.well-known/oauth-client",
  "client_name": "Example MCP Client",
  "client_uri": "https://example.com",
  "logo_uri": "https://example.com/logo.png",
  "redirect_uris": ["http://localhost:3333/callback"],
  "grant_types": ["authorization_code"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none"
}
```

Only public authorization-code clients using PKCE are supported through CIMD.

### Scopes

| Scope            | Grants                                             |
| ---------------- | -------------------------------------------------- |
| `quizzes:read`   | View quizzes and questions                         |
| `quizzes:write`  | Create and edit quizzes and questions              |
| `study:read`     | View study sessions, progress, and statistics      |
| `study:write`    | Record answers and run study sessions              |
| `user:read`      | View user profile and settings                     |

Default scopes when none are requested: `quizzes:read`, `user:read`. A tool call
that needs a scope the token lacks returns a `403` with a message naming the
missing scope.

The consent screen lets the user approve a **subset** of the requested scopes
(each is an individual checkbox), so a token may end up narrower than requested —
handle missing-scope `403`s gracefully and re-request authorization if needed.

Users can review and revoke connected apps via `GET /api/oauth/authorized-apps/`
and `DELETE /api/oauth/authorized-apps/<client_id>/`.

## Tools

All IDs are UUID strings. Tools return a plain object; on failure they return
`{"error": "..."}` rather than raising — surface that message to the user.

### Reading

- `list_my_quizzes()` — the user's own quizzes.
- `search_quizzes(query)` — public quizzes (and the user's own / shared) matching
  a title. Unlisted-with-link quizzes belonging to others are **not** returned.
- `get_quiz(quiz_id)` / `get_quiz_questions(quiz_id)` — full content.
- `list_folders()` / `get_folder_quizzes(folder_id)` — folder structure.
- `get_my_profile()` / `get_my_settings()` — user info (requires `user:read`).

### Authoring (`quizzes:write`)

Everything created through MCP is flagged **`is_ai_generated=true`** so the UI can
label it and users can audit AI-authored content — both the question (and via
`create_quiz`, the quiz itself).

- `create_quiz(title, description="", visibility=2, questions=None)` — create a
  quiz, optionally with all its questions in one atomic call. The quiz is flagged
  `is_ai_generated=true`. Visibility: `0` private, `1` shared-only, `2` unlisted
  (with link, the default), `3` public.
- `add_questions(quiz_id, questions)` — **preferred** way to add multiple
  questions. Atomic: if any item is invalid, nothing is saved and the error names
  the offending index.
- `add_question(quiz_id, text, ...)` — add a single question.
- `edit_question(question_id, text=, explanation=, answers=, tf_answer=)` — update
  in place; only provided fields change.
- `delete_question(question_id)`, `add_quiz_to_folder(quiz_id, folder_id)`.

#### Question shape

```jsonc
// closed (multiple-choice); set is_correct on the right options
{
  "text": "Which are prime?",
  "question_type": "closed",
  "answers": [
    {"text": "2", "is_correct": true},
    {"text": "3", "is_correct": true},
    {"text": "4", "is_correct": false}
  ],
  "explanation": "optional"
}

// open (free text); list the accepted answers — matching is case/whitespace-insensitive
{"text": "Capital of Poland?", "question_type": "open",
 "answers": [{"text": "Warsaw"}, {"text": "Warszawa"}]}

// true/false; use tf_answer, not answers
{"text": "The Earth is flat.", "question_type": "true_false", "tf_answer": false}
```

Rules enforced server-side:
- `closed` needs ≥2 answers and ≥1 correct; `multiple` is auto-enabled when more
  than one answer is correct.
- `open` needs ≥1 accepted answer.
- `true_false` needs a boolean `tf_answer`.

### Studying (`study:read` to read, `study:write` to record/reset)

- `get_quiz_session(quiz_id)` — start/resume a session; returns counts and the
  current question.
- `get_next_question(quiz_id)` — fetch a question to present.
- `submit_answer(quiz_id, question_id, selected_answers)` — record an answer and
  get correctness plus the next question. Pass:
  - closed → list of selected answer UUIDs
  - true_false → `[true]` or `[false]`
  - open → `["the typed answer"]`
- `reset_quiz_session(quiz_id)` — archive the current session and start fresh.
- `get_random_question()` — a random question from recently studied quizzes.

### Progress (`study:read`)

- `get_quiz_progress(quiz_id)` — session counts, scores, study time.
- `get_quiz_statistics(quiz_id)` — aggregates with per-question breakdown.

## Guidance for agents

- Confirm intent before writing. Show the user the questions you plan to create
  and mention they will be labeled AI-generated.
- Batch writes: use `create_quiz(..., questions=[...])` or `add_questions` instead
  of many single calls.
- New quizzes default to **unlisted** (`visibility=2`); only set `3` (public) when
  the user explicitly wants the quiz publicly searchable.
- On an `error` result, read the message and adjust — don't retry the same call.
