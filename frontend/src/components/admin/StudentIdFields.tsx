"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { REGISTER_PREFIX } from "@/lib/registerNumber";

const input = "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm disabled:bg-gray-100";
const part = "rounded-md bg-gray-100 px-2 py-2 text-sm font-semibold text-gray-700";

/**
 * A drop-down that can also be typed in: the arrow opens the list of the batches there are, a click picks one, and
 * anything typed is the value too (a new batch). Typing narrows the list; ArrowUp/ArrowDown, Enter and Escape work.
 */
export function BatchCombobox({
  id,
  value,
  onChange,
  options,
  testId = "student-batch",
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(true); // opened with the arrow: every batch; typing narrows the list
  const [active, setActive] = useState(-1);
  const box = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const typed = value.trim().toLowerCase();
  const shown = showAll || !typed ? options : options.filter((o) => o.toLowerCase().includes(typed));
  const listId = `${id}-list`;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  function pick(batch: string) {
    onChange(batch);
    setOpen(false);
    setActive(-1);
  }

  function toggle() {
    setShowAll(true);
    setActive(-1);
    setOpen(!open);
    inputRef.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setShowAll(true);
        setOpen(true);
        setActive(0);
      } else {
        setActive(Math.min(active + 1, shown.length - 1));
      }
    } else if (e.key === "ArrowUp" && open) {
      e.preventDefault();
      setActive(Math.max(active - 1, 0));
    } else if (e.key === "Enter" && open && shown[active] !== undefined) {
      e.preventDefault(); // pick the highlighted batch, don't submit the form
      pick(shown[active]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div ref={box} className="relative mt-1">
      <input
        ref={inputRef}
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        maxLength={100}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setShowAll(false);
          setActive(-1);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        placeholder="01"
        className={`${input} pr-9`}
        data-testid={testId}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label="Show the batches"
        onClick={toggle}
        className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-gray-500 hover:text-gray-800"
        data-testid={`${testId}-toggle`}
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      {open && (options.length === 0 || shown.length > 0) && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border border-gray-300 bg-white py-1 text-sm shadow-lg"
        >
          {options.length === 0 && <li className="px-3 py-1.5 text-gray-500">No batches yet. Type one.</li>}
          {shown.map((o, i) => (
            <li
              key={o}
              role="option"
              aria-selected={o === value.trim()}
              // mousedown, not click: the input must not lose focus (and close the list) before the pick.
              onMouseDown={(e) => {
                e.preventDefault();
                pick(o);
              }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-1.5 ${i === active ? "bg-blue-50" : ""} ${
                o === value.trim() ? "font-semibold text-blue-700" : ""
              }`}
            >
              {o}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A student's batch and register number. The register number is TST/<batch>/<own number>, e.g. TST/01/001: TST is
 * fixed, the middle part is the batch (picked from the drop-down of the batches there are, or typed) and filled in
 * here as soon as it is known, and only the last part is typed.
 */
export default function StudentIdFields({
  idPrefix,
  batch,
  onBatchChange,
  own,
  onOwnChange,
  batches,
}: {
  idPrefix: string;
  batch: string;
  onBatchChange: (batch: string) => void;
  own: string;
  onOwnChange: (own: string) => void;
  batches: string[];
}) {
  const shownBatch = batch.trim();
  return (
    <div className="grid gap-3">
      <div>
        <label className="block text-sm font-semibold" htmlFor={`${idPrefix}-batch`}>
          Batch <span className="font-normal text-gray-500">(pick one or type)</span>
        </label>
        <BatchCombobox id={`${idPrefix}-batch`} value={batch} onChange={onBatchChange} options={batches} />
      </div>
      <div>
        <label className="block text-sm font-semibold" htmlFor={`${idPrefix}-own-number`}>
          Register number <span className="font-normal text-gray-500">(only the last part; no two students can share it, even in different batches)</span>
        </label>
        <div className="mt-1 flex items-center gap-1" data-testid="register-number">
          <span className={part}>{REGISTER_PREFIX}</span>
          <span aria-hidden="true">/</span>
          <span className={`${part} min-w-10 text-center`} data-testid="register-batch-part">
            {shownBatch || "--"}
          </span>
          <span aria-hidden="true">/</span>
          <input
            id={`${idPrefix}-own-number`}
            maxLength={40}
            value={own}
            disabled={!shownBatch}
            onChange={(e) => onOwnChange(e.target.value)}
            placeholder={shownBatch ? "001" : "batch first"}
            className={`min-w-0 flex-1 ${input}`}
            data-testid="student-own-number"
          />
        </div>
      </div>
    </div>
  );
}
