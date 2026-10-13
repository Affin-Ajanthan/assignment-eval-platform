"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "autoeval.useRubricModel";

/**
 * On/off state for the rubric grading model (local Ollama / Claude) during
 * auto-evaluation. Off = the built-in heuristic grader scores the rubric;
 * the rest of the pipeline runs either way. Remembered per browser so the
 * single-submission and whole-assignment panels share the same setting.
 */
export function useRubricModelSetting(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(true);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved !== null) setOn(saved === "1");
    } catch {
      // storage unavailable: keep the default (on)
    }
  }, []);

  function update(next: boolean) {
    setOn(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // not persisted; still applies to this page
    }
  }

  return [on, update];
}

export default function RubricModelToggle({
  on,
  onChange,
  disabled = false,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-3 flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Rubric grading model"
        disabled={disabled}
        onClick={() => onChange(!on)}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${
          on ? "bg-blue-600" : "bg-gray-300"
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
            on ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
      <div className="text-sm">
        <span className="font-semibold">Rubric grading model: {on ? "On" : "Off"}</span>
        <p className="text-gray-600">
          {on
            ? "Rubric scores come from the AI grading model (slower)."
            : "Rubric scores come from the built-in heuristic grader (fast, no AI model). All other checks still run."}
        </p>
      </div>
    </div>
  );
}
