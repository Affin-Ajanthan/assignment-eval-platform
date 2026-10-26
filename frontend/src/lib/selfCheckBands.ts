import { SelfCheckBand, SelfCheckKind } from "@/lib/api";

/** Colour and wording of each self-check band. */
export const BAND_STYLE: Record<SelfCheckBand, { cls: string; similarity: string; ai: string }> = {
  low: { cls: "bg-green-100 text-green-800 border-green-300", similarity: "Low similarity", ai: "Low likelihood" },
  moderate: {
    cls: "bg-yellow-100 text-yellow-800 border-yellow-300",
    similarity: "Moderate similarity",
    ai: "Moderate likelihood",
  },
  high: { cls: "bg-red-100 text-red-800 border-red-300", similarity: "High similarity", ai: "High likelihood" },
};

/** Left border of the student's own highlighted code lines and report passages. */
export const HIGHLIGHT_BORDER: Record<SelfCheckBand, string> = {
  low: "border-green-400",
  moderate: "border-yellow-400",
  high: "border-red-400",
};

// What each band means for the student. Similarity is symmetric -- an original
// author matches whoever copied them -- so "high" never reads as an accusation.
export const MEANING: Record<SelfCheckBand, { code: string; report: string }> = {
  high: {
    code: "Your code closely matches at least one other submission. If this is your own work, you don't need to do anything: your instructor reviews every match.",
    report: "Your report closely matches at least one other report. If this is your own work, you don't need to do anything: your instructor reviews every match.",
  },
  moderate: {
    code: "Parts of your code are more similar to another submission than is usual for this assignment. Check that the highlighted parts are your own work.",
    report: "Parts of your report are more similar to another report than is usual for this assignment. Check that the highlighted passages are your own words or properly cited.",
  },
  low: {
    code: "Your code doesn't stand out: it only shares the kind of patterns most solutions to this assignment have.",
    report: "Your report doesn't stand out: it only shares the kind of wording most reports for this assignment have.",
  },
};

/** The three self-checks, in the order they are shown. */
export const CHECKS: { kind: SelfCheckKind; label: string; button: string }[] = [
  { kind: "code_similarity", label: "Code similarity", button: "Check my code" },
  { kind: "report_similarity", label: "Report similarity", button: "Check my report" },
  { kind: "ai_content", label: "AI-content detection", button: "Check for AI content" },
];
