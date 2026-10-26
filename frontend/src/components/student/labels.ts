import { SubmissionType } from "@/lib/api";

/** How each kind of upload is named to students. */
export const TYPE_LABEL: Record<SubmissionType, string> = { code: "Code", report: "Report", video: "Presentation video" };

/** Which upload form is open, and for which assignment. */
export type OpenForm = { id: number; mode: "submit" | "edit" } | null;
