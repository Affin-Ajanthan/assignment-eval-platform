"use client";

import { TextareaHTMLAttributes, UIEvent, useRef } from "react";

/**
 * A code box with line numbers down its left side. The numbers follow the text's own lines, so the box must
 * not wrap long lines (give it wrap="off"); they scroll together with the text. Takes the props of a textarea.
 */
export default function LineNumberedTextarea({
  value,
  className = "",
  onScroll,
  ...props
}: { value: string } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value">) {
  const numbers = useRef<HTMLDivElement>(null);
  const lines = value.split("\n").length;

  function handleScroll(e: UIEvent<HTMLTextAreaElement>) {
    if (numbers.current) numbers.current.scrollTop = e.currentTarget.scrollTop;
    onScroll?.(e);
  }

  return (
    <div className="relative mt-1 overflow-hidden rounded-md border border-gray-300 bg-white" data-testid="code-box">
      {/* Same font, line height and top padding as the text, so each number sits beside its line. The extra
          bottom padding lets the numbers scroll as far as the text does when it has a horizontal scroll bar. */}
      <div
        ref={numbers}
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-12 select-none overflow-hidden border-r border-gray-200 bg-gray-50 pb-8 pr-2 pt-3 text-right font-mono text-sm leading-5 text-gray-400"
        data-testid="line-numbers"
      >
        {Array.from({ length: lines }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        value={value}
        onScroll={handleScroll}
        className={`block w-full overflow-auto bg-white py-3 pl-14 pr-3 font-mono text-sm leading-5 ${className}`}
        {...props}
      />
    </div>
  );
}
