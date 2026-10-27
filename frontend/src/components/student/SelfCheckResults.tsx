"use client";

import { useState } from "react";
import { SelfCheck, SelfCheckBand } from "@/lib/api";
import Badge from "@/components/Badge";
import { BAND_STYLE, HIGHLIGHT_BORDER, MEANING } from "@/lib/selfCheckBands";

export function Band({ band, ai = false }: { band: SelfCheckBand; ai?: boolean }) {
  const style = BAND_STYLE[band];
  return <Badge tone={`border ${style.cls}`}>{ai ? style.ai : style.similarity}</Badge>;
}

// How many matching code ranges / report passages are shown before "Show more".
const FIRST_SHOWN = 3;

function ShowMore({ total, all, onToggle }: { total: number; all: boolean; onToggle: () => void }) {
  if (total <= FIRST_SHOWN) return null;
  return (
    <button type="button" onClick={onToggle} aria-expanded={all} className="mt-1 text-xs font-semibold text-blue-700 hover:underline">
      {all ? "Show fewer" : `Show ${total - FIRST_SHOWN} more`}
    </button>
  );
}

/** A code or report similarity result: band, what it means, and the student's own matching parts. */
export function SimilarityResult({ check }: { check: SelfCheck }) {
  const [all, setAll] = useState(false);
  const r = check.result!;
  const band = r.band ?? "low";
  const part = check.kind === "code_similarity" ? "code" : "report";
  const highlights = r.highlights ?? [];
  const passages = r.passages ?? [];
  return (
    <div className="mt-2 text-sm">
      <p>
        <Band band={band} />{" "}
        {r.note ? r.note : `Compared with ${r.compared} other submission(s); ${r.similar_submissions} stand out as similar.`}
      </p>
      {!r.note && <p className="mt-1 text-gray-700">{MEANING[band][part]}</p>}
      {r.small_class && !r.note && (
        <p className="mt-1 text-xs text-gray-600">
          Only {r.compared} other submission(s) to compare with, so this check can&apos;t tell yet what is normal for this
          assignment. The result may change as more classmates submit.
        </p>
      )}
      {check.kind === "code_similarity" && highlights.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-gray-700">Parts of your code with potential matches</p>
          {(all ? highlights : highlights.slice(0, FIRST_SHOWN)).map((h, i) => (
            <div key={i} className="mt-1">
              <p className="text-xs text-gray-500">
                {h.file}, lines {h.start_line}–{h.end_line}
                {h.truncated ? " (first lines shown)" : ""}
              </p>
              <pre
                className={`overflow-x-auto rounded border-l-4 bg-gray-50 px-3 py-2 text-xs ${HIGHLIGHT_BORDER[band]}`}
              >
                {h.text}
              </pre>
            </div>
          ))}
          <ShowMore total={highlights.length} all={all} onToggle={() => setAll(!all)} />
        </div>
      )}
      {check.kind === "report_similarity" && passages.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-gray-700">Passages of your report with potential matches</p>
          {(all ? passages : passages.slice(0, FIRST_SHOWN)).map((text, i) => (
            <blockquote
              key={i}
              className={`mt-1 border-l-4 bg-gray-50 px-3 py-2 text-xs text-gray-700 ${HIGHLIGHT_BORDER[band]}`}
            >
              {text}
            </blockquote>
          ))}
          <ShowMore total={passages.length} all={all} onToggle={() => setAll(!all)} />
        </div>
      )}
      <p className="mt-2 text-xs text-gray-500">
        An indicator, not proof of plagiarism: common code patterns and shared course material can match too. Your
        instructor reviews every result and it never changes your mark by itself.
      </p>
    </div>
  );
}

/** An AI-content result: one band for the report, one for the code. */
export function AiResult({ check }: { check: SelfCheck }) {
  const r = check.result!;
  return (
    <div className="mt-2 text-sm">
      <ul className="space-y-1">
        <li>
          Report: {r.report ? <Band band={r.report} ai /> : <span className="text-gray-500">not assessed</span>}
        </li>
        <li>
          Code: {r.code ? <Band band={r.code} ai /> : <span className="text-gray-500">not assessed</span>}
        </li>
      </ul>
      <p className="mt-2 text-xs text-gray-500">
        Statistical estimates of machine-generated text. They can be wrong, especially for formal or non-native
        English writing and for tidy code, and they never change your mark.
      </p>
    </div>
  );
}
