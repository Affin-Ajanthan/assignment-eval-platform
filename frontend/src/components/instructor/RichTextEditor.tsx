"use client";

import { KeyboardEvent, useLayoutEffect, useRef, useState } from "react";
import RichText, { SIZE_PREFIX, TextSize } from "@/components/RichText";

/** A new text and the part of it to leave selected. */
type Edit = { value: string; start: number; end: number };

const SIZES: { value: TextSize; label: string }[] = [
  { value: "small", label: "Small" },
  { value: "normal", label: "Normal" },
  { value: "large", label: "Large" },
  { value: "larger", label: "Larger" },
  { value: "largest", label: "Largest" },
];

const SIZE_MARK = /^(#{1,3} |-# )/;
const BULLET_MARK = /^\s*[-*] /;
const NUMBER_MARK = /^\s*\d+[.)] /;

/** Put `marker` on both sides of the selection, or take it off when it is already there. */
function wrap(value: string, start: number, end: number, marker: string, placeholder: string): Edit {
  const before = value.slice(0, start);
  const selected = value.slice(start, end);
  const after = value.slice(end);
  const stars = Math.min(/\*+$/.exec(before)?.[0].length ?? 0, /^\*+/.exec(after)?.[0].length ?? 0);
  const present =
    marker === "**" ? stars >= 2 : marker === "*" ? stars % 2 === 1 : before.endsWith(marker) && after.startsWith(marker);
  if (present) {
    const n = marker.length;
    return { value: before.slice(0, -n) + selected + after.slice(n), start: start - n, end: end - n };
  }
  const inner = selected || placeholder;
  const n = marker.length;
  return { value: before + marker + inner + marker + after, start: start + n, end: start + n + inner.length };
}

/** Change the lines the selection touches (`change` gets them and returns the new ones). */
function mapLines(value: string, start: number, end: number, change: (lines: string[]) => string[]): Edit {
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const last = end > start && value[end - 1] === "\n" ? end - 1 : end;
  const found = value.indexOf("\n", last);
  const lineEnd = found === -1 ? value.length : found;
  const block = change(value.slice(lineStart, lineEnd).split("\n")).join("\n");
  return { value: value.slice(0, lineStart) + block + value.slice(lineEnd), start: lineStart, end: lineStart + block.length };
}

function toggleList(value: string, start: number, end: number, ordered: boolean): Edit {
  const mark = ordered ? NUMBER_MARK : BULLET_MARK;
  return mapLines(value, start, end, (lines) => {
    const filled = lines.filter((l) => l.trim() !== "");
    if (filled.length > 0 && filled.every((l) => mark.test(l))) return lines.map((l) => l.replace(mark, ""));
    let n = 0;
    return lines.map((l) => {
      if (l.trim() === "") return l;
      const text = l.replace(BULLET_MARK, "").replace(NUMBER_MARK, "");
      return ordered ? `${++n}. ${text}` : `- ${text}`;
    });
  });
}

function setSize(value: string, start: number, end: number, size: TextSize): Edit {
  return mapLines(value, start, end, (lines) =>
    lines.map((l) => (l.trim() === "" ? l : SIZE_PREFIX[size] + l.replace(SIZE_MARK, ""))),
  );
}

/** The selection as a fenced code block on lines of its own. */
function codeBlock(value: string, start: number, end: number): Edit {
  const selected = value.slice(start, end) || "code here";
  const lead = start > 0 && value[start - 1] !== "\n" ? "\n" : "";
  const trail = end < value.length && value[end] !== "\n" ? "\n" : "";
  const from = start + lead.length + 4; // after the opening fence and its line break
  return {
    value: value.slice(0, start) + lead + "```\n" + selected + "\n```" + trail + value.slice(end),
    start: from,
    end: from + selected.length,
  };
}

/** The most lines the box grows to as the instructor types; longer text scrolls inside it. */
const MAX_LINES = 20;

const tool =
  "rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-800 hover:bg-gray-100 disabled:opacity-60";

/**
 * A text box with a formatting bar for the assignment description: bold, italic, bullet and numbered lists,
 * text size and code (inline or as a block). It writes a small Markdown-like syntax into the text (see
 * RichText, which shows it to students), and Preview shows how it will look.
 */
export default function RichTextEditor({
  id,
  value,
  onChange,
  placeholder,
  rows = 6,
  maxLength,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  maxLength?: number;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [preview, setPreview] = useState(false);

  // The box grows with what is typed, up to MAX_LINES lines; beyond that it scrolls up and down.
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    const fit = () => {
      box.style.height = "auto"; // back to `rows`, so the box can shrink again when text is deleted
      const style = getComputedStyle(box);
      const px = (v: string) => parseFloat(v) || 0;
      const borders = px(style.borderTopWidth) + px(style.borderBottomWidth);
      const padding = px(style.paddingTop) + px(style.paddingBottom);
      const max = (px(style.lineHeight) || 20) * MAX_LINES + padding + borders;
      const wanted = box.scrollHeight + borders;
      box.style.height = `${Math.min(wanted, max)}px`;
      box.style.overflowY = wanted > max ? "auto" : "hidden";
    };
    fit();
    window.addEventListener("resize", fit); // a narrower box wraps the text onto more lines
    return () => window.removeEventListener("resize", fit);
  }, [value, preview]);

  /** Run an edit on the current selection, then put the selection back on what it changed. */
  function apply(edit: (value: string, start: number, end: number) => Edit) {
    const box = ref.current;
    if (!box) return;
    const next = edit(value, box.selectionStart, box.selectionEnd);
    if (maxLength !== undefined && next.value.length > maxLength) return;
    onChange(next.value);
    requestAnimationFrame(() => {
      box.focus();
      box.setSelectionRange(next.start, next.end);
    });
  }

  const bold = () => apply((v, s, e) => wrap(v, s, e, "**", "bold text"));
  const italic = () => apply((v, s, e) => wrap(v, s, e, "*", "italic text"));
  const code = () =>
    apply((v, s, e) => (v.slice(s, e).includes("\n") ? codeBlock(v, s, e) : wrap(v, s, e, "`", "code")));

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === "b") bold();
    else if (key === "i") italic();
    else return;
    e.preventDefault();
  }

  return (
    <div className="mt-1" data-testid="rich-text-editor">
      <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Text formatting">
        <button type="button" onClick={bold} disabled={preview} title="Bold (Ctrl+B)" aria-label="Bold" className={`${tool} font-bold`}>
          B
        </button>
        <button type="button" onClick={italic} disabled={preview} title="Italic (Ctrl+I)" aria-label="Italic" className={`${tool} italic`}>
          I
        </button>
        <select
          aria-label="Text size"
          title="Text size (applies to the selected lines)"
          value=""
          disabled={preview}
          onChange={(e) => apply((v, s, en) => setSize(v, s, en, e.target.value as TextSize))}
          className={tool}
        >
          <option value="" disabled>
            Size
          </option>
          {SIZES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => apply((v, s, e) => toggleList(v, s, e, false))} disabled={preview} title="Bullet list" className={tool}>
          • List
        </button>
        <button type="button" onClick={() => apply((v, s, e) => toggleList(v, s, e, true))} disabled={preview} title="Numbered list" className={tool}>
          1. List
        </button>
        <button type="button" onClick={code} disabled={preview} title="Code font (inline for one line, a block for several)" className={`${tool} font-mono`}>
          {"</>"}
        </button>
        <button type="button" onClick={() => apply(codeBlock)} disabled={preview} title="Code block" className={`${tool} font-mono`}>
          {"{ }"}
        </button>
        <span className="ml-auto flex gap-1">
          <button
            type="button"
            onClick={() => setPreview(false)}
            aria-pressed={!preview}
            className={`${tool} ${!preview ? "border-blue-500 text-blue-700" : ""}`}
          >
            Write
          </button>
          <button
            type="button"
            onClick={() => setPreview(true)}
            aria-pressed={preview}
            className={`${tool} ${preview ? "border-blue-500 text-blue-700" : ""}`}
          >
            Preview
          </button>
        </span>
      </div>

      {preview ? (
        <div
          className="mt-1 max-h-[26rem] min-h-[8rem] overflow-y-auto rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-800"
          data-testid="rich-text-preview"
        >
          {value.trim() ? <RichText text={value} /> : <span className="text-gray-500">Nothing to preview yet.</span>}
        </div>
      ) : (
        <textarea
          ref={ref}
          id={id}
          rows={rows}
          maxLength={maxLength}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="mt-1 block w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm leading-5"
        />
      )}
      <p className="mt-1 text-xs text-gray-500">
        Select text, then use the buttons: **bold**, *italic*, lists, text size and code font. Students see the
        formatted text.
      </p>
    </div>
  );
}
