"use client";

import { Assignment, TestCase } from "@/lib/api";
import TestCasesEditor, {
  MAX_TESTS,
  TestCasePayload,
  TestCaseRow,
  testRowsPayload,
  toTestRows,
} from "@/components/instructor/TestCasesEditor";

/** One question of a code challenge as edited in the form, with its own test cases. */
export type QuestionRow = {
  title: string;
  statement: string;
  tests: TestCaseRow[];
};

export const MAX_QUESTIONS = 20; // must match the backend's _QUESTIONS_MAX

export const emptyQuestionRow = (): QuestionRow => ({ title: "", statement: "", tests: [] });

/** The questions of an existing challenge, each with the test cases that name it. A challenge made without questions has one. */
export function toQuestionRows(a: Pick<Assignment, "questions" | "test_cases">): QuestionRow[] {
  const questions = a.questions?.length ? a.questions : [{ id: 1, title: "", statement: "" }];
  return questions.map((q) => ({
    title: q.title,
    statement: q.statement,
    tests: toTestRows((a.test_cases ?? []).filter((t) => (t.question ?? 1) === q.id)),
  }));
}

type QuestionsPayload =
  | { questions: { title: string; statement: string }[]; tests: (TestCasePayload & Pick<TestCase, "question">)[]; error: null }
  | { questions: null; tests: null; error: string };

/** The questions and all their tests as the API expects them (a test names its question by its place), or the first problem to show. */
export function questionRowsPayload(rows: QuestionRow[]): QuestionsPayload {
  const many = rows.length > 1;
  const tests: (TestCasePayload & Pick<TestCase, "question">)[] = [];
  for (const [i, row] of rows.entries()) {
    const where = many ? `Question ${i + 1}: ` : "";
    if (row.tests.length === 0) {
      const error = many ? `Question ${i + 1} needs at least one test case.` : "Add at least one test case to a code challenge.";
      return { questions: null, tests: null, error };
    }
    const payload = testRowsPayload(row.tests);
    if (payload.error !== null) return { questions: null, tests: null, error: `${where}${payload.error}` };
    tests.push(...payload.tests.map((t) => ({ ...t, question: i + 1 })));
  }
  if (tests.length > MAX_TESTS) {
    return { questions: null, tests: null, error: `An assignment can have at most ${MAX_TESTS} test cases in all (you have ${tests.length}).` };
  }
  return { questions: rows.map((r) => ({ title: r.title.trim(), statement: r.statement })), tests, error: null };
}

const field = "mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm";
const button = "rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-60";

/**
 * The questions of a code challenge. Each has an optional title and description (what the student must write)
 * and its own test cases. The student answers every question in the code editor and one Submit hands them all in;
 * the mark is the points of all the test cases passed, over all the questions.
 */
export default function QuestionsEditor({
  rows,
  onChange,
  locked,
}: {
  rows: QuestionRow[];
  onChange: (rows: QuestionRow[]) => void;
  /** Students have already submitted: their code is saved per question, so questions can't be added or removed. */
  locked: boolean;
}) {
  const update = (i: number, patch: Partial<QuestionRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const totalTests = rows.reduce((sum, r) => sum + r.tests.length, 0);
  const many = rows.length > 1;

  return (
    <fieldset className="mt-3" data-testid="questions-editor">
      <legend className="text-sm font-semibold">Questions and test cases</legend>
      <p className="text-xs text-gray-500">
        A code challenge can ask one question or several. Students answer every question in the code editor, and one
        Submit hands them all in; the mark is the points of all the test cases passed, over all the questions. Each test
        runs the student&apos;s program with the input below (as if typed on the keyboard) and compares its output. Use
        &ldquo;Output contains&rdquo; for menu-driven programs that print prompts. Hidden tests are never shown to
        students. The assignment page shows no test case at all, so put what students need to know in the description
        of the challenge or of the question. When a student presses Run, every test case of that question runs: they see
        how many passed out of the total, and for a visible test that fails its expected and actual output; a hidden
        test that fails is only counted. Submit is final: it runs every test case of every question the same way and
        saves the points of the tests passed as the student&apos;s mark at once, and the student cannot change the code
        afterwards. A question left empty earns nothing.
      </p>

      <div className="mt-2 space-y-4">
        {rows.map((row, i) => (
          <div key={i} className="rounded-md border border-gray-300 bg-gray-50 p-3" data-testid="question-block">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-bold">
                Question {i + 1}
                {row.title.trim() && <span className="ml-2 font-normal text-gray-600">{row.title.trim()}</span>}
              </span>
              {many && (
                <button
                  type="button"
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  disabled={locked}
                  title={locked ? "Students have already submitted, so questions can't be removed" : undefined}
                  className={button}
                >
                  Remove question
                </button>
              )}
            </div>

            <label className="mt-2 block text-xs font-semibold" htmlFor={`question-${i}-title`}>
              Title <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id={`question-${i}-title`}
              value={row.title}
              maxLength={200}
              placeholder={many ? `Question ${i + 1}` : "Palindrome checker"}
              onChange={(e) => update(i, { title: e.target.value })}
              className={field}
            />

            <label className="mt-2 block text-xs font-semibold" htmlFor={`question-${i}-statement`}>
              Description <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <textarea
              id={`question-${i}-statement`}
              value={row.statement}
              rows={4}
              maxLength={10000}
              placeholder="What the student must write. It is shown above the code box."
              onChange={(e) => update(i, { statement: e.target.value })}
              className={field}
            />

            <TestCasesEditor
              rows={row.tests}
              onChange={(tests) => update(i, { tests })}
              idPrefix={`q${i}-`}
              canAdd={totalTests < MAX_TESTS}
            />
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onChange([...rows, emptyQuestionRow()])}
          disabled={locked || rows.length >= MAX_QUESTIONS}
          title={locked ? "Students have already submitted, so questions can't be added" : undefined}
          className={button}
        >
          + Add question
        </button>
        <span className="text-xs text-gray-600">
          {rows.length} question{rows.length === 1 ? "" : "s"} · {totalTests} test case{totalTests === 1 ? "" : "s"} in all
          (at most {MAX_TESTS})
        </span>
      </div>
      {locked && (
        <p className="mt-1 text-xs text-gray-500">
          Students have already submitted, so questions can&apos;t be added or removed. You can still change their wording
          and test cases.
        </p>
      )}
    </fieldset>
  );
}
