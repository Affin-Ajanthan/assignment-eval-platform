"use client";

import { KeyboardEvent, useRef } from "react";

export type AdminTab = "subjects" | "instructors" | "students";

const TABS: { id: AdminTab; label: string }[] = [
  { id: "subjects", label: "Subjects" },
  { id: "instructors", label: "Instructors" },
  { id: "students", label: "Students" },
];

export function isAdminTab(value: string | null): value is AdminTab {
  return TABS.some((t) => t.id === value);
}

/** The props of one tab's panel. Hidden panels stay mounted, so a half-filled create form survives a tab switch. */
export function adminPanelProps(id: AdminTab, current: AdminTab) {
  return { id: `admin-tabpanel-${id}`, role: "tabpanel", "aria-labelledby": `admin-tab-${id}`, hidden: id !== current };
}

/** The tab bar of the admin dashboard, with how many of each there are. Arrow keys, Home and End move between the tabs. */
export default function AdminTabs({
  tab,
  onChange,
  counts,
}: {
  tab: AdminTab;
  onChange: (tab: AdminTab) => void;
  counts: Record<AdminTab, number>;
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
      aria-label="Admin sections"
      onKeyDown={onKeyDown}
      className="mt-6 flex flex-wrap gap-1 border-b border-gray-200"
      data-testid="admin-tabs"
    >
      {TABS.map((t) => {
        const active = t.id === tab;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            id={`admin-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`admin-tabpanel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={`-mb-px flex-1 rounded-t-md border px-3 py-2 text-sm font-semibold sm:flex-none sm:px-4 ${
              active
                ? "border-gray-200 border-b-white bg-white text-blue-700"
                : "border-transparent text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            {t.label}
            <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-700">
              {counts[t.id]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
