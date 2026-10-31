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
    cli.py               standalone CLI: python -m app.similarity.cli check <dir> (the website's comparison)
  evaluator/            the multi-modal evaluator
    report_analysis.py   PDF/DOCX text+image extraction, AI-text heuristic
    code_analysis.py     static analysis (complexity, docstrings, style)
    rubric_grading.py    heuristic grader (fallback) + local Ollama grader (qwen3:8b)
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
tests/                  871 tests; 23 marked `slow` use real models and skip gracefully offline
sample_submissions/     demo data for the standalone similarity CLI
```

## Run it

Backend:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend settings can be kept in a `.env` file in the project folder (next
to `requirements.txt`): copy `.env.example` to `.env`, change what you
need, and start the server with `--env-file`:

```bash
uvicorn app.main:app --reload --port 8000 --env-file .env
```

`.env` is not committed (it is in `.gitignore`), so each computer keeps
its own. A setting that is already set on the computer (for example with
`setx`) wins over the same setting in `.env`.

If a change to a Python file seems to have no effect (a page says *Not Found*
for a route that should exist, or a new field is ignored when you save), the
backend is still running old code: stop it with Ctrl+C and start it again.
`--reload` can stop noticing changes without saying so; adding `--reload-dir app`
makes it watch only the code folder. A new database column is added by itself
when the backend starts.

### Concurrent auto-evaluation

"Evaluate a whole assignment" grades every **submission** (student) of
one assignment. By default it grades them one after another; to grade
several students at the same time, two settings must match:

| Setting | Read by | Where to set it |
|---|---|---|
| `AUTO_EVAL_WORKERS` | the backend | `.env` (or `setx`), then restart the backend |
| `OLLAMA_NUM_PARALLEL` | Ollama (a separate program; it does not read the project's `.env`) | `setx OLLAMA_NUM_PARALLEL 2` (Windows) or the environment Ollama starts in, then restart Ollama |

**Use the same number for both** for the best result. With
`AUTO_EVAL_WORKERS=4` but `OLLAMA_NUM_PARALLEL=1`, four submissions are
prepared at once but the model still grades them one at a time (the
others wait in Ollama's queue). With `OLLAMA_NUM_PARALLEL` higher than
`AUTO_EVAL_WORKERS`, Ollama reserves memory the backend never uses.

Marks are unaffected: each submission is still graded by the same model
and prompt; only the total waiting time changes. All parallel gradings
share one GPU, and each one needs its own context memory
(`OLLAMA_NUM_CTX`, 8192 tokens by default), so the right number depends
on the GPU:

| GPU memory | Suggested value for both settings |
|---|---|
| 6 GB (qwen3:8b does not fully fit even alone) | 2, or 1 |
| 12 GB | about 2 |
| 16-24 GB | 3-4 |

These are starting points, not measurements: time a batch with 1 and
with your chosen number, and keep the higher one only if it is clearly
faster. While a batch runs, `ollama ps` shows the loaded model.

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
   against the chosen rubric. The similarity flag from step 4 is shown
   as a review flag; it never changes the marks (the same rule for every
   grader). The result (recommended score, review flags, per-criterion
   breakdown) is stored and shown on the dashboard.
   **Whole assignment at once** ("Evaluate a whole assignment"):
   evaluates every submission of that assignment (run the similarity
   check first so its flags feed the grading) as a **background job**,
   so a large class with a local LLM doesn't keep the instructor waiting
   on the page:
   - `POST /subjects/{id}/assignments/{name}/auto-evaluate/jobs` with
     `{"rubric_id": ...}` starts the job and answers at once (202, status
     `queued`).
   - `GET /auto-evaluate/jobs/{job_id}` reports its progress: status
     (`queued` / `running` / `done` / `failed` / `interrupted`), `done` of
     `total`, the evaluated / skipped / failed counts, and each finished
     submission's result in submission order (`null` while still waiting).
     The page polls it every 3 s to show a progress bar and fill in the
     results table.
   - `GET /subjects/{id}/assignments/{name}/auto-evaluate/jobs/latest`
     returns the assignment's latest run, so the page shows it again after
     the instructor leaves and comes back.
   - Only one run per assignment at a time: starting another while one is
     queued or running is refused (409).
   - Each result is saved as it is produced and one failing submission
     never stops the rest. If the server stops mid-run, the job is marked
     `interrupted` at the next start (so it no longer blocks the
     assignment), and `POST /auto-evaluate/jobs/{job_id}/resume` grades the
     rest with the same settings, skipping submissions already evaluated.
     Note that `uvicorn --reload` restarts the server whenever a code file
     is saved, which interrupts a running job.
   - Every run is recorded in the `batch_jobs` table.

   `POST /subjects/{id}/assignments/{name}/auto-evaluate` runs the same
   job but waits until every submission is done and returns all results
   at once (kept for scripts; the page uses the job endpoints). Send
   `"skip_already_evaluated": true` with either to skip submissions that
   already have an evaluation with this rubric.
   Submissions are evaluated `AUTO_EVAL_WORKERS` at a time (default 1:
   one after another); see "Concurrent auto-evaluation" below to grade
   several students of the assignment at once.
6. **Manual grading**: the instructor reviews the auto-evaluation --
   they can accept its scores as a starting point (one click copies
   them into the grading form) or override them entirely -- and saves
   the final grade via `POST /submissions/{id}/grade`. The manual grade
   is always what counts; auto-evaluation is a second opinion, never
   the final word.

Every one of these endpoints is scoped: an instructor can only act on
subjects an admin assigned them to, and a student can only submit to
and see their own work in subjects they're enrolled in.

### Code challenges (HackerRank-style test cases)

Creating an assignment starts with a choice, fixed once the assignment exists:

- **Submission**: students upload code, a report and/or a video; it is graded
  with a rubric (everything described above).
- **Code challenge**: students submit **code only**. It is run against the
  instructor's **test cases**, and the **points of the tests passed are the
  mark**. A challenge has **no rubric**: the server refuses a rubric on it, and
  refuses the rubric Grade form, the single Auto-evaluate and "Evaluate a whole
  assignment" for it (400, "A code challenge is marked from its tests").

**Test cases** (1 to 50 per challenge in all, set in the assignment form): a name, the
**input** fed to the program's standard input, the **expected output**, a
**match** mode, **visible** or hidden, and **points**. `exact` compares the whole
output (trailing spaces, line-ending style and surrounding blank lines are
ignored); `contains` looks for the expected text anywhere in the output, which
suits menu programs that print prompts. The instructor can name the **main
file** to run (e.g. `student_management.rb`); left empty, the only runnable
(Python, Ruby, Java, JavaScript, C or C++) file in the submission is used, or one named `main`, `app`, `run`, `program` or
`index`.

**Tasks.** A challenge has **one task or several** (up to 20), all in the one
assignment. Each task has its own **question** (what the student must write, shown
above the code box), an optional **title**, and its **own test cases** (input and
expected output); the mark is the points of the test cases passed **over all the
tasks**, so an instructor weights a task by the points of its tests. A challenge
made without tasks has one. In the API and the database a task is called a
*question*: a test case's `question` (1, 2, ...) names the task it belongs to, and
`questions` holds the titles and question texts (`title`, `statement`) in
`POST` / `PUT /assignments` (the tests must cover every task, and a task can't be
left without a test). The *number* of tasks is fixed once a student has
submitted, because their code is saved per task; the wording and the test cases
can always be fixed. A challenge with several tasks is answered on its code page
only (a plain file upload is refused), and "Main file to run" is ignored for it.

**Languages: Python, Ruby, Java, JavaScript, C and C++, for now.** Other
languages can be submitted to a normal assignment, but a challenge cannot run them
yet. Java runs with the JDK's single-file launcher (`java main.java`: compiled in
memory, then run, so the file name need not match the class, and the first class
needs a `public static void main`); JavaScript runs with Node (`node main.js`).
C (`gcc -std=c17`) and C++ (`g++ -std=c++17`) are compiled inside the test's
container and then run; only the one main file is compiled, so a challenge in C or
C++ is a single source file (headers from the standard library only). Pull
`eclipse-temurin:21-jdk`, `node:20-slim` and `gcc:13` once (see `.env.example`). A
Java test gets 5 extra seconds for the JVM to start and compile. A program that
does not compile or crashes is shown to the student as **Compiler error. Error on
line N.**, whatever the language (a C/C++ crash such as a segfault has no line, so
it shows **Compiler error.**).

**Students** do a code challenge on **its own page** (`/student/code/{id}`). The
assignment card shows **no question and no description**: it has a **Do
assignment** button (**Continue assignment** once some tasks are handed in), and
the questions are first shown on the page it opens. (This only keeps them off the
card: `GET /assignments` still carries the text, because the page needs it and
nothing records a "start".) On the page the student does **one task at a time**.
The typed code is saved as `main.py` / `main.rb` / `main.java` / `main.js` / `main.c` / `main.cpp`, or `q1.py`, `q2.rb`, ... when
there are several tasks. With several tasks the page shows a **tab for each**, with
the task's question; every task has its own code and language, and they can be
done in any order. Each task has two buttons:

- **Run** (`POST /assignments/{id}/run-code`, with the task's `question` number)
  runs the typed code of the open task against **every test case of that task,
  hidden ones included**, and always tells the student how many
  passed out of the total ("3 of 3 test cases passed: all passed", or "2 of 5
  test cases passed"). For each **visible** test that failed it adds just its
  **expected output and actual output** (plus the error message if the program
  crashed or ran out of time). A failing **hidden** test is only counted ("2
  hidden test cases did not pass"). Run is practice: no submission is made and
  no mark changes, and the result is dropped as soon as the code is edited (or
  the page is left).
- **Submit** (`POST /assignments/{id}/submit-code`, body `{"question": 1, "code":
  "...", "language": "python"}`; `question` is the first when left out) hands in
  **that task**, after a "Submit your code?" confirmation, because it is
  **final**. The server saves the code as the student's answer (the first task
  handed in creates the student's one submission for the assignment, the others
  add a file to it), runs the task against its own test cases and **saves the
  points of the tests passed** with the answer. The submission's **mark** is the
  points of the tests passed in all the answers **over the points of all the
  tasks' tests** (the instructor sets the points on each test case; 8 of 10
  tests worth 2 points each is 16 of 20). A task not handed in yet earns
  nothing for now, but its points are already in the total, so "Your mark so
  far: 6 / 10" goes up as the other tasks are handed in. The page shows the
  result at once: "Submitted", "X of Y test cases passed" (with the same
  expected-vs-actual for failing visible tests), the points of that answer and
  the mark so far. The task's box locks and shows the code that was handed in,
  and a button leads on to the next task still to do. If the instructor set a
  **marks release date**, the student still sees the test results, but the
  points and the mark wait for that date.

`GET /assignments/{id}/my-code` gives the page what was handed in so far (the
code, the report and the points of each task, and the mark so far), so it can be
closed and reopened, and still shows the results after the deadline. The reports
are kept with the submission (`Submission.question_results`, see
`app/code_answers.py`), so nothing is run again to show them.

**A task that is handed in cannot be changed.** There is no Edit or Delete for
a challenge's submission: `PUT` and `DELETE /submissions/{id}` are refused (409),
and `can_edit` is always false. A second Submit of the same task is refused
too (409); the other tasks can still be handed in until the deadline, and a
task not handed in by then earns nothing. Submit uses **none of the student's
hourly runs** (so a student who practised with every run can still submit), and
when the server is busy it **waits for a free place** (up to 2 minutes) rather
than being refused. If the tests cannot be run at all (the sandbox is off or
down, the server stayed busy, an error) the code is **still handed in**, without
a result. The page then shows **Get my marks** under that answer, and the card
says the code has no mark yet (`POST /assignments/{id}/mark-my-code`): it runs
the same marking on every handed-in answer that has no result yet (never on one
that has, so a result cannot change), works after the deadline too, and refuses
(409) when every answer already has its result. The instructor can press **Run
and save as mark** instead. The same lock applies to a challenge handed in as a
plain file upload through `POST /submissions` (which does not mark it). A
submission made before answers were kept one by one (all at once, or uploaded as
files) has no per-task record: the page works its answers out from its files,
it cannot be added to, and Get my marks gives it its per-task results.

The assignment card shows how many tasks are handed in ("1 of 3 tasks
submitted") and links to the page: **Do assignment**, **Continue assignment**
while tasks are left, and **See your code and result** afterwards (also after
the deadline).

**The student portal never lists the test cases.** The assignment card shows
no sample input or expected output, before or after submitting (the server does
not send them; the question of each task is what students read up front, on the
task's page).
The only way a student sees a visible test's expected output is the result of a
Run in which that test fails. Limits on Run, since every run
starts a Docker container per test case: one run at a time per student,
`CODE_SAMPLE_RUNS_PER_HOUR` (10) per student, and `CODE_SAMPLE_MAX_PARALLEL` (2)
at once on the server (a Submit's marking run counts towards that cap and goes
before new practice runs). Every Run of every task uses one of the hourly
runs, so a challenge with several tasks may need a higher
`CODE_SAMPLE_RUNS_PER_HOUR`. The counts are in memory and start again when the
backend restarts.

**Hidden tests never leave the server.** Students receive a visible test's
expected and actual output only when it fails in a Run, and only how *many*
hidden tests failed; a run returns no test ids, points or inputs that could
hint at them, and a hidden test's error output is never shown. The
instructor's view shows every test.

**Instructors**: a student's code is already marked when they hand a task in (see
above), so nothing has to be done for a normal submission. Open **Tests** on a
submission to look at every result, or to mark again (for example after fixing a
test case, or for a submission that was left unmarked):

- `POST /submissions/{id}/run-tests` runs every test and returns each result
  (expected vs actual output, error output, status `passed` / `failed` /
  `error` / `timeout`, or `skipped` for a task the student left empty) and the
  score, overall and task by task (`questions`). The panel groups the
  results by task. It changes nothing.
- `POST /submissions/{id}/mark-from-tests` does the same and **saves the points
  of the tests passed as the mark** (e.g. 12 of 16; 8 of 10 tests worth 2
  points each is 16 of 20) and sets the submission to graded. Running it again
  replaces the mark, and the result of every task the student handed in (so
  what they see per task follows it); it never hands a task in for them.
  The student sees it like any mark, including the assignment's marks release
  date; there is no per-criterion breakdown. It is stored on the submission
  (`test_earned`, `test_total`, `tests_run_at`, and `question_results` for each
  answer). Changing the points of a test case later does not change marks
  already saved: mark again to apply it.

**The sandbox.** Running student code is **off by default**: set
`CODE_SANDBOX=docker` in `.env`, start Docker Desktop (Docker is needed only on
the machine that runs the backend, not for browsers) and pull the images once:

```bash
docker pull python:3.12-slim
docker pull ruby:3.3-slim
```

Without it, students see "Running code is not available right now." and
instructors see "Code execution is off. Set CODE_SANDBOX=docker...". Each test
runs in its own container with **no network, 256 MB of memory (no swap), 0.5
CPU, 64 processes, a read-only filesystem, all Linux capabilities dropped, an
unprivileged user and a time limit** (`CODE_TEST_TIMEOUT`, 10 s). The code is
mounted read-only and copied to a small in-memory scratch folder, so programs
that save and load files still work and nothing one test writes is seen by the
next. There is no "run it locally" fallback. If Docker is running but cannot
start a test container (for example the image was never pulled and there is no
internet), the tests count as *not run*, never as failed, so no mark of 0 is
saved by mistake. Settings: `CODE_SANDBOX`,
`CODE_TEST_TIMEOUT`, `CODE_SANDBOX_IMAGE`, `CODE_SANDBOX_RUBY_IMAGE`,
`CODE_SAMPLE_RUNS_PER_HOUR`, `CODE_SAMPLE_MAX_PARALLEL` (see `.env.example`).

### Token code similarity (Winnowing)

Both the instructor's similarity check and the student self-check
fingerprint each file the same way (`app/similarity_runs.py`):

- **Junk code is removed first** -- unused variables and imports, `if
  (false)` blocks, code after a `return` -- with the same cleanup the
  semantic check uses (`python_cleanup.py`, `ts_cleanup.py`), so padding
  a copy no longer lowers its Jaccard. Removed code keeps its line
  breaks, so highlights still show the student's real line numbers.
- **Tokens come from tree-sitter** for Java, JavaScript, C, C++, C#, Go,
  Ruby and PHP (Python: its own tokenizer; other languages: a regex
  fallback). Names fold to one token, strings and numbers too, comments
  are dropped, and each language's own keywords are kept -- PHP's
  `$name`, JavaScript's template strings and C's `#include` are read
  correctly. Code with a syntax error is still tokenized.

### Semantic code similarity (UniXcoder)

Winnowing fingerprints (Jaccard + containment) catch literal and
renamed copies, but a copy that's been rewritten -- functions
reordered, loops restructured -- can share few k-grams with its
source. `app/similarity/semantic.py` adds Microsoft's
`microsoft/unixcoder-base-nine` (9 languages: Python, Java, JavaScript, PHP,
Ruby, Go, C, C++, C#; pinned to one revision) as an extra signal:

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
  the only **"high"** ones. No similarity flag changes marks in
  auto-evaluation, for any grader -- they are shown as review flags
  ("potential similarity detected -- lecturer review recommended").

The model (~500 MB) downloads once on first use (it's preloaded in
the background at startup) and is cached by Hugging Face afterwards.
If it can't be loaded or inference fails, the check still returns the
fingerprint/Jaccard/containment results with a warning. Set
`SEMANTIC_SIMILARITY=0` to turn it off.

Encoding is the slow part of a check (about 2 s per submission on a CPU;
comparing the pairs takes well under a second). Each submission's vectors
are therefore kept in `cache/unixcoder/` (one small file per submission,
vectors only, no code), so a repeat check -- or the first one after a
server restart -- needs no model inference and does not even load the
model. A change to the code, the model or the chunking creates a new entry.
Only one inference pass runs at a time, so students who check at the same
moment share it instead of each re-encoding the class. `SEMANTIC_CACHE_DIR`
moves the folder (`off` keeps everything in memory) and
`SEMANTIC_CACHE_MAX_MB` (default 500) caps it, deleting the oldest files
first. The folder is safe to delete: it is rebuilt on demand.

Thresholds were calibrated by hand on a small sample (renamed or
restructured copies scored 0.82-0.91; five independently written
solutions to the same task scored up to 0.78), so check them against
a real cohort before relying on them.

### Report similarity (PDF)

`POST /subjects/{id}/assignments/{name}/check-report-similarity`, the
"Check report similarity" button in the instructor's Similarity check
card, compares the PDF reports of one assignment pairwise
(`app/similarity/report_similarity.py`):

1. **Extract** each page's text with PyMuPDF.
2. **Clean**: drop page-number lines and running headers/footers (lines
   near the top or bottom of a page, digits ignored, repeated on at least
   half the pages), rejoin hyphenated words, collapse whitespace.
3. **Winnowing over words** (6-word k-grams, window 5): Jaccard and
   containment, plus the actual **matching passages**: identical runs of
   10+ words, shown side by side. Fingerprints found in most reports
   (the assignment brief, a template) are ignored.
4. **Semantic**: all-MiniLM-L6-v2 embeddings of ~120-word chunks; each
   chunk is matched to its most similar chunk in the other report, in
   both directions, so one copied or paraphrased section scores high.
5. **Combined flag**: "high" for identical passages (Jaccard >= 0.30 or
   containment >= 0.40); "review" for very similar meaning without them
   (>= 0.85, raised by the same cohort-outlier rule as code once there
   are 10+ pairs).

Results are a review signal only: nothing is stored, so report
similarity never changes a mark. DOCX reports, scanned PDFs (no text
layer) and reports under 50 words are listed as not compared. The
semantic part shares the MiniLM model with cross-modal consistency, so
`CROSS_MODAL_SEMANTIC=0` turns it off too. The thresholds are
**uncalibrated**; check them against real reports before relying on them.

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
small local language model, `Qwen/Qwen2.5-1.5B` by default (about 3 GB,
downloaded once). **It is on by default** as the planned upgrade from the
style heuristic. Caution: on a small calibration sample the 0.5B version
did no better than the style heuristic, and the 1.5B version's scores
still overlapped heavily between AI and human text. Its false-flag rate
on real student reports has not been measured. Set `AI_TEXT_DETECTION=0`
to return to the style heuristic.

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

Two stages in the plan assume an LLM or a downloaded ML model: rubric
grading and video transcription (Whisper). Rather than hard-requiring
those, both are small interfaces with:

- a **working, fully offline default** (a keyword-overlap grader, an
  empty transcript) so the whole app runs with zero setup and zero
  cost, and
- a **real backend that's picked up automatically** once available:
  - **Rubric grading** -- `build_default_grader()` picks, in order:
    1. the **local Ollama model `qwen3:8b`** when the Ollama server is
       reachable and the model is installed (`ollama pull qwen3:8b`) --
       free, offline, nothing leaves the machine;
    2. the keyword-overlap heuristic grader, when Ollama is not available.

    `GRADER_FEWSHOT=on` adds six hand-written calibration examples to the
    grading prompt. It is **off by default**: on 299 human-graded short
    answers it made the small model worse (mean error 1.54 -> 1.87 marks of
    5) because it more often claimed "no answer was provided".

    Force one with `GRADER_BACKEND=ollama|heuristic`; change the local
    model or server with `OLLAMA_MODEL` / `OLLAMA_URL`. The grader used is
    stored with every auto-evaluation (`ollama` or `heuristic`).
  - **Video transcription** -- install `faster-whisper`: Whisper `small`
    runs on CUDA (float16) when an NVIDIA GPU is available and on CPU
    (int8) otherwise; a failed GPU load retries once on CPU. It needs
    network access to download the model on first use. If transcription
    fails for any reason, the video stage continues with an empty
    transcript (backend `null`, reason kept in `TranscriptionResult.error`)
    and the frame analysis, so an evaluation never crashes on it.
  - **Video frame descriptions (vision)** -- a video with no speech has an
    empty transcript. When a local vision model is installed
    (`ollama pull qwen3-vl:4b`, override with `VISION_MODEL`), 4 frames
    spread across the video are downscaled and described by it, and the
    descriptions go to the grader next to the transcript, so a silent
    video can still be judged from what is on screen. It is **off by
    default**, so only the grading model is used; enable it with `VIDEO_VISION=auto`
    (it then runs only if the model is installed).
    The descriptions are machine-generated and the grader is told they may
    be wrong; if the step fails, a review flag says so and grading
    continues on the transcript alone. It costs roughly one model call
    per frame.
  - **Running the code (optional, off by default)** -- the LLM grader can
    only read code. Set `CODE_SANDBOX=docker` and each submission's `.py`
    files (at most 3) are run in a throw-away Docker container (no network,
    read-only filesystem, code mounted read-only, all capabilities dropped,
    unprivileged user, 256 MB / 0.5 CPU / 64 processes, 10 s limit). The
    real exit code, stdout and stderr go to the grader as an EXECUTION
    RESULT it may cite, and a crash or timeout adds a review flag. If Docker
    is not running nothing is executed -- there is no unsandboxed fallback --
    and a review flag says so. Image: `CODE_SANDBOX_IMAGE`
    (default `python:3.12-slim`).

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

There are 871 tests. The 848 not marked `slow` pass offline
(`python -m pytest tests/ -m "not slow"`; accounts/roles/subject-scoping, report/code
analysis, similarity fingerprinting, rubric grading -- both the
heuristic grader and the Ollama grader against a fake HTTP post, so no
Ollama server or network call is needed. `conftest.py` sets
`GRADER_BACKEND=heuristic` so ordinary tests never call a real model --
video frame
analysis, cross-modal consistency, the full pipeline, and the FastAPI
endpoints including similarity-check and auto-evaluate). The 23 tests
marked `slow` exercise real models (e.g. `faster-whisper` transcription,
UniXcoder, a running Ollama, Docker for the code-challenge sandbox) and skip (not fail) when a model can't be
downloaded or reached, which is exactly what happens in a
network-restricted sandbox -- they pass in a normal deployment.
`conftest.py` gives every test run its own empty database and uploads
folder in a temporary directory, removed at the end, so the real
`portal.db` and `uploads/` are never opened or changed by tests.

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

- The LLM grader (local qwen3:8b) is given code *metrics* for every
  file (function count, complexity, quality score, issues) and the
  text of the submission in limited amounts: 8,000 characters of source
  code, 6,000 characters of report text and 3,000 characters of
  transcript. When a submission is longer than its limit, the grader
  gets the passages that share the most words with the criteria, in
  their original order, and a note says how many passages were left out
  and that they exist. Word matching is simple: a passage that describes
  a criterion in entirely different words can be missed. Criteria that
  need the code's actual behaviour (e.g. "implements bubble sort
  correctly") can be under-scored. When any input is cut, the submission
  gets a review flag so the instructor checks the marks for those
  criteria. Each grading call requests a context window of
  `OLLAMA_NUM_CTX` tokens (default 8192) so the prompt is not silently
  cut off by Ollama, and a reply of at most `OLLAMA_NUM_PREDICT` tokens
  (default 2000). A grading prompt plus reply is about 6,200 tokens. The
  Qwen3 model card's larger values (40960 / 32768) were measured about 75%
  slower on a 6 GB GPU with no benefit, so they are not the default. Sampling follows the Qwen3 model card's non-thinking
  settings (temperature 0.7, top_p 0.8, top_k 20, min_p 0, plus
  presence_penalty 0.5 against repetition, `OLLAMA_PRESENCE_PENALTY`), so grading the
  same submission twice can give slightly different marks; set
  `OLLAMA_TEMPERATURE=0` for repeatable marks. A timed-out or malformed reply is retried once before
  the submission is marked failed. In our evaluation, qwen3:8b with the
  current grading prompt graded slightly strictly (299 answers from the
  Mohler short-answer set: MAE 0.88 marks out of 5, 69% within 1 mark,
  average 0.54 marks below the human graders, versus MAE 2.31 / 20% for
  a keyword baseline; `eval/results/models_20261020_182000/`). That run
  used temperature 0, before the sampling settings above; keep
  instructor override as the final word.
- Code challenges run **Python, Ruby, Java, JavaScript, C and C++ only**; each test starts its own
  Docker container (about 1-3 seconds), so a long test list takes a while;
  `exact` matching is strict about inner spaces and wording; and the mark
  measures only what the tests check, not code quality, style or a report. A
  student's mark is saved when they submit; marking again after a test case
  changes is done one submission at a time ("Mark all" for a class is not
  built). A submitted challenge is final, and an instructor cannot reopen it
  for a student (not built). Marking a Submit waits at most 2 minutes for a free
  place when many students submit at once; after that the code is kept
  unmarked. The Run limits reset when the backend restarts. The editor is a
  plain code box, without syntax colouring.
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
- Video transcription uses Whisper `small` via `faster-whisper`: on CUDA
  (float16) when a GPU is available, otherwise on CPU (int8); a failed
  GPU load retries once on CPU. It needs network access to download the
  model on first use; without it (or without `faster-whisper`
  installed), the pipeline degrades to an empty transcript
  automatically rather than failing.




Role	Email	Password
Admin	admin@school.local	            Admin@123
Instructor	 instructor@school.local	Instructor@123
Student 1	student1@school.local	       Student1@123
Student 2	student2@school.local      	Student2@123
Student 3	student3@school.local	      Student3@123



The CUDA libraries I installed aren’t in requirements.txt. That’s on purpose: they’re about 1 GB and only help on machines with an NVIDIA GPU. Without them Whisper still works, just slowly on the CPU, and the backend console now says so. If teammates with NVIDIA GPUs want the speed-up, they can run this once:

pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"