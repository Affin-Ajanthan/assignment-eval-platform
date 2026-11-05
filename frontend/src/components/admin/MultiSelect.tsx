"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";

export type MultiOption = { id: number; label: string; detail?: string };

/**
 * A drop-down to pick several things: the ones picked show as chips (each with a x to remove it), typing narrows
 * the list, and a click or Enter adds or removes the one in the list. The list stays open so more can be picked.
 * ArrowUp/ArrowDown move, Enter picks, Escape closes, Backspace in the empty box removes the last chip.
 */
export default function MultiSelect({
  id,
  options,
  selected,
  onChange,
  placeholder = "Search and pick...",
  emptyText = "Nothing to pick yet.",
  testId,
}: {
  id: string;
  options: MultiOption[];
  selected: Set<number>;
  onChange: (next: Set<number>) => void;
  placeholder?: string;
  emptyText?: string;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const box = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const wanted = query.trim().toLowerCase();
  const shown = wanted
    ? options.filter((o) => `${o.label} ${o.detail ?? ""}`.toLowerCase().includes(wanted))
    : options;
  const chips = options.filter((o) => selected.has(o.id));
  const listId = `${id}-list`;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  function toggle(optionId: number) {
    const next = new Set(selected);
    if (next.has(optionId)) next.delete(optionId);
    else next.add(optionId);
    onChange(next);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        setActive(0);
      } else {
        setActive(Math.min(active + 1, shown.length - 1));
      }
    } else if (e.key === "ArrowUp" && open) {
      e.preventDefault();
      setActive(Math.max(active - 1, 0));
    } else if (e.key === "Enter" && open && shown[active] !== undefined) {
      e.preventDefault(); // pick the highlighted one, don't submit the form
      toggle(shown[active].id);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    } else if (e.key === "Backspace" && !query && chips.length > 0) {
      toggle(chips[chips.length - 1].id);
    }
  }

  return (
    <div ref={box} className="relative mt-1">
      <div
        className="flex min-h-[2.5rem] flex-wrap items-center gap-1 rounded-md border border-gray-300 bg-white px-2 py-1 focus-within:border-blue-500"
        onClick={() => inputRef.current?.focus()}
      >
        {chips.map((o) => (
          <span
            key={o.id}
            className="inline-flex items-center gap-1 rounded bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-800"
            data-testid="multi-chip"
          >
            {o.label}
            <button
              type="button"
              aria-label={`Remove ${o.label}`}
              onClick={(e) => {
                e.stopPropagation();
                toggle(o.id);
              }}
              className="text-blue-700 hover:text-red-700"
            >
              ×
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={chips.length === 0 ? placeholder : ""}
          className="min-w-[8rem] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none"
          data-testid={testId}
        />
        <button
          type="button"
          tabIndex={-1}
          aria-label="Show the list"
          onClick={(e) => {
            e.stopPropagation();
            setOpen(!open);
            inputRef.current?.focus();
          }}
          className="flex h-6 w-6 items-center justify-center text-gray-500 hover:text-gray-800"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}>
            <path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-multiselectable="true"
          className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-gray-300 bg-white py-1 text-sm shadow-lg"
        >
          {options.length === 0 && <li className="px-3 py-1.5 text-gray-500">{emptyText}</li>}
          {options.length > 0 && shown.length === 0 && (
            <li className="px-3 py-1.5 text-gray-500">No match for &quot;{query.trim()}&quot;.</li>
          )}
          {shown.map((o, i) => {
            const on = selected.has(o.id);
            return (
              <li
                key={o.id}
                role="option"
                aria-selected={on}
                // mousedown, not click: the input must not lose focus (and close the list) before the pick.
                onMouseDown={(e) => {
                  e.preventDefault();
                  toggle(o.id);
                }}
                onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 ${i === active ? "bg-blue-50" : ""}`}
              >
                <span
                  aria-hidden="true"
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border text-xs ${
                    on ? "border-blue-600 bg-blue-600 text-white" : "border-gray-400 bg-white"
                  }`}
                >
                  {on ? "✓" : ""}
                </span>
                <span className={on ? "font-semibold" : undefined}>
                  {o.label}
                  {o.detail && <span className="ml-2 text-xs font-normal text-gray-500">{o.detail}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
