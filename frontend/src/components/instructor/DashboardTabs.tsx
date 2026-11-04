"use client";

import { KeyboardEvent, useRef } from "react";

export type DashboardTab = "grading" | "integrity" | "batch" | "setup";

const TABS: { id: DashboardTab; label: string }[] = [
  { id: "grading", label: "Submissions & grading" },
  { id: "integrity", label: "Similarity" },
  { id: "batch", label: "Batch evaluate" },
  { id: "setup", label: "Assignments & rubrics" },
];

export function isDashboardTab(value: string | null): value is DashboardTab {
  return TABS.some((t) => t.id === value);
}

/** The props of one tab's panel. Hidden panels stay mounted, so a running check or an unsaved grade survives a tab switch. */
export function tabPanelProps(id: DashboardTab, current: DashboardTab) {
  return { id: `tabpanel-${id}`, role: "tabpanel", "aria-labelledby": `tab-${id}`, hidden: id !== current };
}

/** The tab bar of the instructor dashboard. Arrow keys, Home and End move between the tabs. */
export default function DashboardTabs({
  tab,
  onChange,
  toGrade,
}: {
  tab: DashboardTab;
  onChange: (tab: DashboardTab) => void;
  toGrade: number;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = TABS.findIndex((t) => t.id === tab);
    const to =
      e.key === "ArrowRight" ? (i + 1) % TABS.length
      : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
      : e.key === "Home" ? 0
      : e.key === "End" ? TABS.length - 1
      : null;
    if (to === null) return;
    e.preventDefault();
    onChange(TABS[to].id);
    refs.current[TABS[to].id]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="Dashboard sections"
      onKeyDown={onKeyDown}
      className="mt-4 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-gray-200"
    >
      {TABS.map((t) => {
        const active = t.id === tab;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`tabpanel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={`shrink-0 whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold ${
              active
                ? "border-brand-700 text-brand-700"
                : "border-transparent text-gray-600 hover:border-gray-300 hover:text-gray-900"
            }`}
          >
            {t.label}
            {t.id === "grading" && toGrade > 0 && (
              <span className="ml-2 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-semibold text-yellow-800">
                {toGrade} to grade
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
