"use client";

import { useEffect, useState } from "react";

/** An on/off setting remembered per browser (default on), so the
 * single-submission and whole-assignment panels share it. */
function usePersistentSwitch(storageKey: string): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(true);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved !== null) setOn(saved === "1");
    } catch {
      // storage unavailable: keep the default (on)
    }
  }, [storageKey]);

  function update(next: boolean) {
    setOn(next);
    try {
      window.localStorage.setItem(storageKey, next ? "1" : "0");
    } catch {
      // not persisted; still applies to this page
    }
  }

  return [on, update];
}

function SwitchRow({
  label,
  on,
  onChange,
  disabled,
  onText,
  offText,
}: {
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
  disabled: boolean;
  onText: string;
  offText: string;
}) {
  return (
    <div className="mt-3 flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
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
        <span className="font-semibold">
          {label}: {on ? "On" : "Off"}
        </span>
        <p className="text-gray-600">{on ? onText : offText}</p>
      </div>
    </div>
  );
}

/**
 * On/off state for the rubric grading model (local Ollama) during
 * auto-evaluation. Off = the built-in heuristic grader scores the rubric;
 * the rest of the pipeline runs either way.
 */
export function useRubricModelSetting(): [boolean, (on: boolean) => void] {
  return usePersistentSwitch("autoeval.useRubricModel");
}

/**
 * On/off state for AI-content detection during auto-evaluation. Off = the
 * AI-text model (the slowest step after video transcription) and the code
 * AI heuristic are skipped; cross-modal consistency and everything else run.
 */
export function useAiDetectionSetting(): [boolean, (on: boolean) => void] {
  return usePersistentSwitch("autoeval.useAiDetection");
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
    <SwitchRow
      label="Rubric grading model"
      on={on}
      onChange={onChange}
      disabled={disabled}
      onText="Rubric scores come from the AI grading model (slower)."
      offText="Rubric scores come from the built-in heuristic grader (fast, no AI model). All other checks still run."
    />
  );
}

export function AiDetectionToggle({
  on,
  onChange,
  disabled = false,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <SwitchRow
      label="AI-content detection"
      on={on}
      onChange={onChange}
      disabled={disabled}
      onText="Estimates whether the report and code look machine-generated (adds about a minute per submission)."
      offText="Skipped. Cross-modal consistency, rubric grading and all other checks still run."
    />
  );
}
