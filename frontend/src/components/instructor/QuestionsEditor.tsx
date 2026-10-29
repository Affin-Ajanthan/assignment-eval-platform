"use client";

import { Assignment, TestCase } from "@/lib/api";
import { ownTitle } from "@/lib/tasks";
import AutoGrowTextarea from "@/components/AutoGrowTextarea";
import RichTextEditor from "@/components/instructor/RichTextEditor";
import TestCasesEditor, {
  MAX_TESTS,
  TestCasePayload,
  TestCaseRow,
  testRowsPayload,
  toTestRows,
} from "@/components/instructor/TestCasesEditor";

/** One task of a code challenge as edited in the form: its title, its question and its own test cases. */
export type QuestionRow = {
  title: string;
  statement: string; // the question the student must answer in code
  starterCode: string; // "" = the student's code box starts empty
  tests: TestCaseRow[];
};

export const MAX_QUESTIONS = 20; // must match the backend's _QUESTIONS_MAX
const MAX_STARTER_CHARS = 50_000; // must match the backend's _TASK_STARTER_MAX

export const emptyQuestionRow = (): QuestionRow => ({ title: "", statement: "", starterCode: "", tests: [] });

/** The tasks of an existing challenge, each with the test cases that name it. A challenge made without tasks has one. */
export function toQuestionRows(a: Pick<Assignment, "questions" | "test_cases">): QuestionRow[] {
  const questions = a.questions?.length ? a.questions : [{ id: 1, title: "", statement: "", starter_code: "" }];
  return questions.map((q) => ({
    title: ownTitle(q.title), // "Task 2" is only what the server called a task without a title
    statement: q.statement,
    starterCode: q.starter_code ?? "",
    tests: toTestRows((a.test_cases ?? []).filter((t) => (t.question ?? 1) === q.id)),
  }));
}

type QuestionsPayload =
  | { questions: { title: string; statement: string; starter_code: string }[]; tests: (TestCasePayload & Pick<TestCase, "question">)[]; error: null }
  | { questions: null; tests: null; error: string };

/** The tasks and all their tests as the API expects them (a test names its task by its place), or the first problem to show. */
export function questionRowsPayload(rows: QuestionRow[]): QuestionsPayload {
  const many = rows.length > 1;
  const tests: (TestCasePayload & Pick<TestCase, "question">)[] = [];
  for (const [i, row] of rows.entries()) {
    const where = many ? `Task ${i + 1}: ` : "";
    if (!row.title.trim()) return { questions: null, tests: null, error: `${where}Enter a title for the task.` };
    if (!row.statement.trim()) return { questions: null, tests: null, error: `${where}Enter the question for the task.` };
    if (row.tests.length === 0) {
      const error = many ? `Task ${i + 1} needs at least one test case.` : "Add at least one test case to a code challenge.";
      return { questions: null, tests: null, error };
    }
    const payload = testRowsPayload(row.tests);
    if (payload.error !== null) return { questions: null, tests: null, error: `${where}${payload.error}` };
    tests.push(...payload.tests.map((t) => ({ ...t, question: i + 1 })));
  }
  if (tests.length > MAX_TESTS) {
    return { questions: null, tests: null, error: `An assignment can have at most ${MAX_TESTS} test cases in all (you have ${tests.length}).` };
  }
  const questions = rows.map((r) => ({ title: r.title.trim(), statement: r.statement, starter_code: r.starterCode }));
  return { questions, tests, error: null };
}

const field = "mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm";
const button = "rounded-md bg-gray-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700 disabled:opacity-60";

/**
 * The tasks of a code challenge. At least one is required, and each needs a title, its own question (what the
 * student must write) and its own test cases (input and expected output). The student sees the questions only after pressing Do
 * assignment, then hands the tasks in one at a time, each marked as soon as it is submitted; the mark is the
 * points of all the test cases passed, over all the tasks.
 */
export default function QuestionsEditor({
  rows,
  onChange,
  locked,
}: {
  rows: QuestionRow[];
  onChange: (rows: QuestionRow[]) => void;
  /** Students have already submitted: their code is saved per task, so tasks can't be added or removed. */
  locked: boolean;
}) {
  const update = (i: number, patch: Partial<QuestionRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const totalTests = rows.reduce((sum, r) => sum + r.tests.length, 0);
  const many = rows.length > 1;

  return (
    <fieldset className="mt-3" data-testid="questions-editor">
      <legend className="text-sm font-semibold">Tasks and test cases</legend>
      <p className="text-xs text-gray-500">
        A code challenge needs at least one task. Each task has a title, its own question and its own test cases (input
        and expected output), all required. Students see the questions only after they press Do assignment, and they hand the tasks in one
        at a time; the mark is the points of all the test cases passed, over all the tasks. Each test runs the
        student&apos;s program with the input below (as if typed on the keyboard) and compares its output. Use
        &ldquo;Output contains&rdquo; for menu-driven programs that print prompts. Hidden tests are never shown to
        students. No test case is shown at all, so put what students need to know in the question. When a student presses
        Run, every test case of that task runs: they see how many passed out of the total, and for a visible test that
        fails its expected and actual output; a hidden test that fails is only counted. Submit is final: it runs every
        test case of that task the same way and saves the points of the tests passed at once, and the student cannot
        change that task&apos;s code afterwards. A task that is not handed in earns nothing.
      </p>

      <div className="mt-2 space-y-4">
        {rows.map((row, i) => (
          <div key={i} className="rounded-md border border-gray-300 bg-gray-50 p-3" data-testid="question-block">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-bold">
                Task {i + 1}
                {row.title.trim() && <span className="ml-2 font-normal text-gray-600">{row.title.trim()}</span>}
              </span>
              {many && (
                <button
                  type="button"
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  disabled={locked}
                  title={locked ? "Students have already submitted, so tasks can't be removed" : undefined}
                  className={button}
                >
                  Remove task
                </button>
              )}
            </div>

            <label className="mt-2 block text-xs font-semibold" htmlFor={`question-${i}-title`}>
              Title <span className="font-normal text-red-600">(required)</span>
            </label>
            <input
              id={`question-${i}-title`}
              value={row.title}
              maxLength={200}
              placeholder="Palindrome checker"
              onChange={(e) => update(i, { title: e.target.value })}
              className={field}
            />

            <label className="mt-2 block text-xs font-semibold" htmlFor={`question-${i}-statement`}>
              Question <span className="font-normal text-red-600">(required)</span>
            </label>
            <RichTextEditor
              id={`question-${i}-statement`}
              value={row.statement}
              rows={5}
              maxLength={10000}
              placeholder="What the student must write. It is shown above the code box, after the student presses Do assignment."
              onChange={(text) => update(i, { statement: text })}
            />

            <label className="mt-2 block text-xs font-semibold" htmlFor={`question-${i}-starter`}>
              Starting code <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <AutoGrowTextarea
              id={`question-${i}-starter`}
              value={row.starterCode}
              rows={6}
              maxLength={MAX_STARTER_CHARS}
              spellCheck={false}
              placeholder={"def solve(n):\n    # write your code here\n    pass"}
              onChange={(e) => update(i, { starterCode: e.target.value })}
              className={`${field} font-mono`}
            />
            <p className="mt-1 text-xs text-gray-500">
              Put in this task&apos;s code box when the student opens it, so they write on top of it. Empty: the box
              starts empty.
            </p>

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
          title={locked ? "Students have already submitted, so tasks can't be added" : undefined}
          className={button}
        >
          + Add task
        </button>
        <span className="text-xs text-gray-600">
          {rows.length} task{rows.length === 1 ? "" : "s"} · {totalTests} test case{totalTests === 1 ? "" : "s"} in all
          (at most {MAX_TESTS})
        </span>
      </div>
      {locked && (
        <p className="mt-1 text-xs text-gray-500">
          Students have already submitted, so tasks can&apos;t be added or removed. You can still change their wording
          and test cases.
        </p>
      )}
    </fieldset>
  );
}
