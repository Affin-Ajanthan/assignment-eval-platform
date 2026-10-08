# AI-Assisted Assignment Evaluation Platform

One application implementing every phase of the platform plan ("AI-Assisted
Assignment Evaluation Platform -- Plan"): accounts with role-based access
(admin/instructor/student) and subject-wise separation, a submission
portal, a rubric engine, code-similarity detection, report/code/video
analysis, rubric grading, cross-modal consistency, and manual grading
with instructor override -- a FastAPI backend with one database, and a
Next.js/TypeScript frontend.

## Layout

```
app/
  main.py              FastAPI app: accounts/subjects, rubrics, submissions,
                        grading, similarity checks, auto-evaluation (all endpoints)
  db.py                 SQLAlchemy engine/session + the declarative Base
  models.py             User/Subject/InstructorAssignment/Enrollment/AuthSession,
                        plus Rubric/Submission/Grade/SimilarityFlag/AutoEvaluation
  auth.py                password hashing, session tokens, role-based
                        FastAPI dependencies, default-admin bootstrap
  similarity/           offline code-similarity detection
    core.py             tokenize -> normalize -> k-gram winnowing fingerprints
    ai_heuristics.py     experimental AI-generated-code style heuristic
    semantic.py          UniXcoder semantic similarity (extra review signal)
    cli.py               standalone CLI: python -m app.similarity.cli check <dir>
  evaluator/            the multi-modal evaluator
    report_analysis.py   PDF/DOCX text+image extraction, AI-text heuristic
    code_analysis.py     static analysis (complexity, docstrings, style)
    rubric_grading.py    heuristic grader (default) + pluggable LLM grader
    video_analysis.py    frame/scene analysis + pluggable transcription
    cross_modal.py       code/report/video consistency check (keyword overlap)
    semantic_consistency.py  same check by meaning (MiniLM embeddings)
    pipeline.py           aggregates every stage into one graded result
frontend/               Next.js 16 / React 19 / TypeScript / Tailwind app
  src/app/login/          single login page, redirects by role
  src/app/admin/          create subjects, instructors, students; assign subjects
  src/app/student/        upload code/report/video for an enrolled subject
  src/app/instructor/     rubrics, similarity check, auto-evaluate, manual grading
  src/lib/api.ts          shared API client (bearer token, session handling)
  (see frontend/README.md for frontend-specific run instructions)
tests/                  66 tests, 1 real-model test that skips gracefully offline
sample_submissions/     demo data for the standalone similarity CLI
```

## Run it

Backend:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

On first run the server prints a default admin login to the console
(see "Accounts and access control" below). API docs are auto-generated
at `http://localhost:8000/docs`.

Frontend (in a separate terminal):

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000/login` and sign in (use `localhost`, not
`127.0.0.1` -- see `frontend/README.md`). Edit `NEXT_PUBLIC_API_BASE` in
`frontend/.env.local` if you deploy the backend somewhere other than
`localhost:8000`.

## Accounts and access control

Every account -- admin, instructor, student -- is created by an admin.
There is no self-registration; people log in with credentials the
admin gave them.

- **Admin**: logs in and lands on `/admin`. Creates subjects, creates
  instructor accounts (assigning them to one or more subjects), and
  creates student accounts (enrolling them in one or more subjects).
  Can also reassign an existing instructor's or student's subjects
  later.
- **Instructor**: logs in and lands on `/instructor`. Only ever sees and
  manages rubrics, submissions, similarity checks and grading for the
  subjects an admin assigned them to -- the dashboard has a subject
  selector at the top that scopes everything below it.
- **Student**: logs in and lands on `/student`. Only ever sees and submits to
  the subjects an admin enrolled them in, and only ever sees their own
  submissions and grades.

On first run, since no accounts exist yet, the server bootstraps a
default admin so there's a way to log in:

```
email:    admin@school.local
password: admin123
```

Change this (or set `ADMIN_BOOTSTRAP_PASSWORD` before first run) before
using this anywhere that matters. Every other endpoint requires an
`Authorization: Bearer <token>` header, obtained from `POST
/auth/login`; the frontend handles this automatically once you're
logged in.

## What each phase looks like here

| Phase (from the plan) | Where |
| --- | --- |
| Accounts + subject-wise access control | `app/auth.py`, `app/models.py`; `/auth/*` and `/admin/*` endpoints in `app/main.py`; `frontend/src/app/login`, `frontend/src/app/admin` |
| Submission portal, rubric upload, manual grading | `app/main.py`: `/rubrics`, `/submissions`, `/submissions/{id}/grade` |
| Pre-submission similarity + AI-content detection | `app/similarity/` (standalone CLI) + `app/main.py`'s `POST /subjects/{id}/assignments/{name}/check-similarity`; AI-text for reports lives in `app/evaluator/report_analysis.py` |
| Automated rubric grading for code + report | `app/evaluator/rubric_grading.py`, run via `POST /submissions/{id}/auto-evaluate` |
| Video pipeline: transcription + content analysis | `app/evaluator/video_analysis.py`, run via the same auto-evaluate endpoint |
| Cross-modal consistency + aggregated grade + instructor override | `app/evaluator/cross_modal.py` + `app/evaluator/pipeline.py`; the instructor dashboard shows the auto-evaluation, then the instructor grades manually (which always wins) |

### The end-to-end flow

1. An admin logs in, creates a subject, creates an instructor account
   assigned to it, and creates student accounts enrolled in it.
2. A student logs in and submits code (a single file or a `.zip`,
   auto-extracted), a report (PDF/DOCX), and a video for one of their
   enrolled subjects.
3. An instructor logs in, picks that subject from the selector at the
   top, and uploads a rubric (Rubrics card).
4. **Similarity check**: the instructor picks an assignment and runs
   `POST /subjects/{id}/assignments/{name}/check-similarity`, which
   fingerprints every code submission for that assignment within that
   subject and flags likely copies (stored in the `similarity_flags`
   table). It also adds a semantic-similarity signal -- see
   "Semantic code similarity" below.
5. **Auto-evaluate**: for one submission, `POST
   /submissions/{id}/auto-evaluate` runs the full pipeline --
   static analysis, AI-text/AI-code heuristics, video frame analysis
   and transcription, cross-modal consistency, and rubric grading --
   against the chosen rubric, folding in the similarity flag from step
   4. The result (recommended score, review flags, per-criterion
   breakdown) is stored and shown on the dashboard.
6. **Manual grading**: the instructor reviews the auto-evaluation --
   they can accept its scores as a starting point (one click copies
   them into the grading form) or override them entirely -- and saves
   the final grade via `POST /submissions/{id}/grade`. The manual grade
   is always what counts; auto-evaluation is a second opinion, never
   the final word.

Every one of these endpoints is scoped: an instructor can only act on
subjects an admin assigned them to, and a student can only submit to
and see their own work in subjects they're enrolled in.

### Semantic code similarity (UniXcoder)

Winnowing fingerprints (Jaccard + containment) catch literal and
renamed copies, but a copy that's been rewritten -- functions
reordered, loops restructured -- can share few k-grams with its
source. `app/similarity/semantic.py` adds Microsoft's
`microsoft/unixcoder-base` as an extra signal:

- Each submission's code is normalized (comments stripped,
  identifiers anonymized), split into overlapping 512-token chunks
  (long files are covered in full, not truncated), and embedded
  **once** -- not once per pair. Embeddings are cached by content, so
  re-running a check never re-encodes an unchanged submission.
- Model inference only runs for submissions that appear in at least
  one pair the token check didn't already flag. Pair scores are
  cosine similarities between stored chunk vectors (order-independent
  best-match), so 50 students = at most 50 encodes for 1,225 pairs
  (about 10 s on CPU after a ~12 s one-time model load).
- A pair the token check didn't flag gets a **"review"** flag when its
  semantic score is at least 0.80 *and* clearly above the rest of
  the cohort (median + 2 robust standard deviations). Token-based flags stay
  the only **"high"** ones, and a semantic-only flag never caps a score
  in auto-evaluation -- it's shown as "potential similarity detected
  -- lecturer review recommended".

The model (~500 MB) downloads once on first use (it's preloaded in
the background at startup) and is cached by Hugging Face afterwards.
If it can't be loaded or inference fails, the check still returns the
fingerprint/Jaccard/containment results with a warning. Set
`SEMANTIC_SIMILARITY=0` to turn it off.

Thresholds were calibrated by hand on a small sample (renamed or
restructured copies scored 0.82-0.91; five independently written
solutions to the same task scored up to 0.78), so check them against
a real cohort before relying on them.

### Cross-modal semantic consistency (MiniLM)

Cross-modal semantic consistency uses a local sentence-embedding model
to compare the meaning of the student's code documentation, written
report, and video transcript. It helps identify whether the submitted
components describe related content. The result is a review signal and
is not evidence of plagiarism or academic misconduct by itself.

Similar wording is not required for a high semantic score because the
model compares semantic representations rather than simple keyword
overlap.

- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (~90 MB, runs
  locally on CPU, downloaded once and cached). Loaded once per process
  -- preloaded in the background at startup -- and shared by every
  evaluation (`app/evaluator/semantic_consistency.py`).
- **Inputs:** code *documentation* only (docstrings and comments from
  Python, Java, C/C++, JS/TS and similar; tool directives, licence
  headers and commented-out code are dropped), the report text the
  existing PDF/DOCX extractor already produced, and the transcript the
  video stage already produced (nothing is transcribed twice).
- **Long documents** are split into sentence-aligned chunks of about
  120 words. Every chunk is embedded and averaged into one vector, so
  the whole report or transcript counts, not just its beginning. Chunk
  embeddings are cached by content hash.
- **Scores:** cosine similarity for Code ↔ Report, Code ↔ Transcript
  and Report ↔ Transcript; the overall score averages only the pairs
  that could be computed. A missing component is reported as
  unavailable (`null` in the API, "—" in the UI) -- never as 0% -- and
  never causes a flag by itself.
- **Status:** `consistent`, `review_recommended` (overall below the
  threshold), `limited_data` (fewer than three components), or
  `unavailable` / `disabled`. "Review recommended" adds a review flag
  but never changes any score.
- **Configuration:** `CROSS_MODAL_SEMANTIC=0` disables it;
  `CROSS_MODAL_CONSISTENCY_THRESHOLD` (default `0.50`) sets the review
  threshold. **The 0.50 default is a prototype value that has not been
  validated on real student submissions.** On the hand-written samples
  in `tests/consistency_samples.py`, matching components scored
  0.66-0.89 and unrelated ones about 0.0, but a handful of samples is
  not validation.
- If the model can't be loaded or embedding fails, the evaluation
  still completes; this section reports itself as unavailable with a
  warning and produces no score.

The older keyword-overlap check (`app/evaluator/cross_modal.py`,
`consistency_score`) is unchanged and still runs alongside it.

#### Report text: Microsoft MarkItDown

The report text used for this comparison is extracted with
[Microsoft MarkItDown](https://github.com/microsoft/markitdown)
(`app/evaluator/document_extraction.py`):

```
PDF / DOCX -> MarkItDown -> Markdown -> plain text -> chunks -> all-MiniLM-L6-v2
```

- MarkItDown only converts documents. It doesn't grade, compare or
  judge anything, and it doesn't replace MiniLM or UniXcoder.
- Extraction runs automatically in the background right after a student
  submits; the student sees nothing of it. The text is stored next to the
  upload (`uploads/<id>/report_extracted.md` + `report_extraction.json`)
  and reused by auto-evaluate, which extracts on demand for submissions
  made before this existed.
- Only MarkItDown's PDF and DOCX converters are enabled (no plugins, no
  LLM, no cloud service), so conversion is local and offline. With
  every built-in converter enabled, MarkItDown would fall back to its
  plain-text converter for a corrupted PDF and return the raw bytes as
  "text".
- If extraction fails (corrupted, empty or scanned-only document, or
  over the `REPORT_EXTRACTION_TIMEOUT` of 60 s), the report is marked
  unavailable for this comparison and the instructor sees why. Everything else
  -- grading, code similarity, video, the other comparisons -- still runs.
- The existing report analysis (AI-text heuristic, figure/image check,
  the text the rubric grader sees) keeps its own PyMuPDF/python-docx
  extraction, so grading is unchanged.

#### Upload validation

Uploads are treated as untrusted. The code must be a `.zip` or a single
source file (50 MB; a zip may unpack to at most 200 MB / 5,000 entries,
and entries pointing outside the submission are skipped). The report
must be a real PDF or DOCX (checked by content, not just extension;
`REPORT_MAX_BYTES`, default 25 MB). The video must be MP4, MOV, AVI,
MKV, WEBM or M4V (1 GB). Filenames are reduced to a safe
base name, so nothing can be written outside `uploads/<id>/`, and a
rejected upload leaves no files behind.

### Report AI-text signal (Fast-DetectGPT)

`app/evaluator/ai_text_detection.py` can estimate whether report text looks
machine-generated using Fast-DetectGPT (Bao et al., ICLR 2024) with a
small local language model, `Qwen/Qwen2.5-0.5B` by default (about 1 GB,
downloaded once, CPU-only). **It is off by default**: on a small
calibration sample it did no better than the style heuristic (AI and
human scores overlapped heavily), so the heuristic remains the default.
Set `AI_TEXT_DETECTION=1` to try it, ideally against real student reports.

- A language model scores how "expected" each word is. AI-written text
  keeps choosing the model's most likely words; human text is spikier.
  The resulting "curvature" is about 0 for human-like text and higher for
  machine-like text.
- The report is scored in 256-token chunks (at most 8, spread across the
  whole report) and averaged, so long reports aren't penalised for length.
  Reports under ~120 tokens are reported as too short to judge.
- Bands: below `AI_TEXT_MEDIUM` (1.0) is low, below `AI_TEXT_HIGH` (2.0)
  medium, above that high. **These are prototype values and haven't been
  validated on real student reports.**
- If the model is off or can't be loaded, the style heuristic is used.
  `AI_TEXT_DETECTOR_MODEL` selects a different (ideally base, not
  instruction-tuned) model.

**This is a review signal, never proof.** AI-text detectors misfire,
notably on formal, template-like and non-native English writing, and are
easily defeated by light editing. AI-content signals (for reports and
code) only add review flags: they never lower the suggested score.

## Design principle: pluggable, honest defaults

Two stages in the plan assume a paid API or a downloaded ML model:
LLM rubric grading (Claude) and video transcription (Whisper). Rather
than hard-requiring those, both are small interfaces with:

- a **working, fully offline default** (a keyword-overlap grader, an
  empty transcript) so the whole app runs with zero setup and zero
  cost, and
- a **real backend that's picked up automatically** once configured:
  set `ANTHROPIC_API_KEY` for LLM grading, install `faster-whisper` for
  real speech-to-text (needs network access to download the model on
  first use).

The AI-content heuristics (for both code and report text) are
explicitly style heuristics, not validated classifiers -- there is no
reliable free/offline substitute for GPTZero-style detection. Every
flag they raise is meant as a prompt for human review, never an
automatic penalty; see the per-module docstrings for the exact
features each one uses.

## Testing

Backend:

```bash
python -m pytest tests/ -v
```

66 tests pass offline (accounts/roles/subject-scoping, report/code
analysis, similarity fingerprinting, rubric grading -- both the
heuristic grader and the LLM grader tested against a fake Anthropic
client, so no API key or network call is needed -- video frame
analysis, cross-modal consistency, the full pipeline, and the FastAPI
endpoints including similarity-check and auto-evaluate). One additional
test exercises real `faster-whisper` transcription end-to-end and skips
(not fails) when the model can't be downloaded, which is exactly what
happens in a network-restricted sandbox -- it would pass in a normal
deployment. `conftest.py` wipes `portal.db` at the start of every test
run so account-creation tests never collide with leftover data from a
previous run.

Frontend:

```bash
cd frontend
npm run build   # production build
npm run lint    # ESLint
```

The frontend was also verified with a full Playwright walkthrough
against a live backend (admin creates accounts -> instructor creates a
rubric -> students submit -> similarity check flags a copy ->
auto-evaluate -> manual grade -> cross-role guard -> wrong-password
rejection), covering the same flow the automated backend tests cover.

## Honest limitations

- `HeuristicRubricGrader` and the AI-content heuristics are keyword/style
  signals, not semantic understanding or validated classifiers. Treat
  every score and flag as a starting point for human review.
- The cross-modal consistency check is vocabulary overlap between code
  identifiers, report text, and video transcript -- deliberately
  simple and auditable (every flag names the exact missing terms)
  rather than an opaque LLM judgment call.
- CORS is wide open (`allow_origins=["*"]`) -- fine for local
  development, not for a real deployment; tighten it to your actual
  frontend origin before deploying anywhere real.
- Password hashing is stdlib PBKDF2-HMAC-SHA256 (no extra dependency);
  sessions are opaque bearer tokens with a 7-day expiry stored in the
  `auth_sessions` table, sent by the frontend from `localStorage`. This
  is a reasonable default for a project this size, not a hardened
  auth system -- there's no password reset flow, no rate limiting on
  login attempts, and no HTTPS enforcement (add a reverse proxy for
  that in a real deployment).
- Video transcription needs network access to download the Whisper
  model on first use; without it (or without `faster-whisper`
  installed), the pipeline degrades to an empty transcript
  automatically rather than failing.
