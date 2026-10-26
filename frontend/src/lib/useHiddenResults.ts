"use client";

import { useEffect, useState } from "react";

// A hidden result is remembered per check (by its id), so it stays hidden after a
// reload but a NEW check of that kind shows again.
const HIDDEN_KEY = "selfcheck.hidden";

function readHidden(): number[] {
  try {
    const raw = window.localStorage.getItem(HIDDEN_KEY);
    return raw ? (JSON.parse(raw) as number[]) : [];
  } catch {
    return [];
  }
}

function writeHidden(ids: number[]) {
  try {
    window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(ids.slice(-200)));
  } catch {
    // storage unavailable: hiding still works until the page is reloaded
  }
}

/** Which self-check results the student has hidden, and a toggle. */
export function useHiddenResults(): [number[], (checkId: number) => void] {
  const [hidden, setHidden] = useState<number[]>([]);

  useEffect(() => setHidden(readHidden()), []);

  function toggle(checkId: number) {
    // Every assignment's panel shares one stored list: start from what is stored
    // now (another panel may have changed it), plus this panel's own state in
    // case storage is unavailable.
    const current = [...new Set([...readHidden(), ...hidden])];
    const next = current.includes(checkId) ? current.filter((id) => id !== checkId) : [...current, checkId];
    setHidden(next);
    writeHidden(next);
  }

  return [hidden, toggle];
}
