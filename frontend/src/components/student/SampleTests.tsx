"use client";

import { SampleTest } from "@/lib/api";

// A test the instructor did not name is stored as "Test 2" (its place among ALL the
// tests, hidden ones included), which means little to a student: show "Sample 1" instead.
const GENERATED_NAME = /^Test \d+$/;

/** "Sample 2: Palindrome with punctuation", or just "Sample 2" for a test without a real name. */
export function sampleLabel(name: string, index: number): string {
  const trimmed = name.trim();
  return !trimmed || GENERATED_NAME.test(trimmed) ? `Sample ${index + 1}` : `Sample ${index + 1}: ${trimmed}`;
}

const pre =
  "mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-white p-2 font-mono text-xs";

/**
 * The visible tests of a code challenge, always open (a student should not have to
 * click to find out what the program must do): each sample's input and expected
 * output. Hidden tests are never sent, so only how many there are can be said.
 */
export default function SampleTests({ samples, hiddenCount }: { samples: SampleTest[]; hiddenCount: number }) {
  if (samples.length === 0 && hiddenCount === 0) return null;
  const hidden = `${hiddenCount} ${samples.length > 0 ? "more " : ""}test${hiddenCount === 1 ? " is" : "s are"} hidden: Run checks your code against ${hiddenCount === 1 ? "it" : "them"} too, but never shows ${hiddenCount === 1 ? "it" : "them"}.`;

  return (
    <div className="mt-3" data-testid="sample-tests">
      <p className="text-sm font-semibold">Sample tests</p>
      <p className="text-xs text-gray-500">
        {samples.length > 0
          ? "Your program reads each input from the keyboard (input() in Python, gets in Ruby) and prints the output. "
          : "No sample is shown for this assignment. "}
        {hiddenCount > 0 && hidden}
      </p>
      {samples.map((t, i) => (
        <div key={i} className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-3" data-testid="sample-test">
          <p className="text-sm">
            <span className="font-semibold">{sampleLabel(t.name, i)}</span>{" "}
            <span className="text-xs text-gray-500">
              {t.points} point{t.points === 1 ? "" : "s"} · {t.match === "contains" ? "output contains" : "exact output"}
            </span>
          </p>
          <div className="mt-1 grid gap-2 sm:grid-cols-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-600">Sample input</p>
              <pre className={pre}>{t.input === "" ? "(none)" : t.input}</pre>
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-600">Expected output</p>
              <pre className={pre}>{t.expected_output}</pre>
            </div>
          </div>
          {t.match === "contains" && (
            <p className="mt-1 text-xs text-gray-500">Your output only has to contain this text.</p>
          )}
        </div>
      ))}
    </div>
  );
}
