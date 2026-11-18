"use client";

import { KeyboardEvent, ReactNode, useRef } from "react";

export type TabSpec<T extends string> = { id: T; label: string; badge?: ReactNode };

/** The props of one tab's panel. Hidden panels stay mounted, so a running check or an unsaved grade survives a tab switch. */
export function tabPanelProps(id: string, current: string) {
  return { id: `tabpanel-${id}`, role: "tabpanel", "aria-labelledby": `tab-${id}`, hidden: id !== current };
}

/** A tab bar for the instructor pages (the subject page and the assignment page). Arrow keys, Home and End move between the tabs. */
export default function PageTabs<T extends string>({
  tabs,
  tab,
  onChange,
  label,
}: {
  tabs: TabSpec<T>[];
  tab: T;
  onChange: (tab: T) => void;
  label: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.id === tab);
    const to =
      e.key === "ArrowRight" ? (i + 1) % tabs.length
      : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0
      : e.key === "End" ? tabs.length - 1
      : null;
    if (to === null) return;
    e.preventDefault();
    onChange(tabs[to].id);
    refs.current[tabs[to].id]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      // The same folder tabs as the admin dashboard (AdminTabs). The line under them is an inset shadow, not a
      // border: the bar scrolls sideways on a phone, which clips anything that hangs over its edge, and the
      // selected tab's white bottom still covers a shadow drawn inside it.
      className="mt-4 flex gap-1 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_var(--color-gray-200)]"
    >
      {tabs.map((t) => {
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
            className={`shrink-0 whitespace-nowrap rounded-t-md border px-4 py-2 text-sm font-semibold ${
              active
                ? "border-gray-200 border-b-white bg-white text-blue-700"
                : "border-transparent text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            }`}
          >
            {t.label}
            {t.badge}
          </button>
        );
      })}
    </div>
  );
}
