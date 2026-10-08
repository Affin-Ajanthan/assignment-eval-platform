"""
The aggregator: ties every stage together into one result for the
instructor dashboard, mirroring the plan's pipeline diagram (all of
D1-D3, E1-E3, F1-F3 feeding into the Aggregator, then "LLM rubric
grading + cross-modal consistency", then the dashboard).

This module deliberately does NOT import ``app.similarity`` directly --
they're conceptually separate stages of the plan's architecture table
(D2/D3 vs. the rest), so `evaluate_submission` takes the
similarity/AI-code flags as plain booleans. The caller (`app/main.py`'s
`POST /submissions/{id}/auto-evaluate` endpoint) computes them by
calling `app.similarity` first and passing the results through -- see
that endpoint for a worked example.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .code_analysis import CodeReport, analyze_directory
from .cross_modal import ConsistencyResult, check_consistency
from .document_extraction import ReportExtraction, extract_report_text
from .report_analysis import ReportAnalysis, analyze_report
from .rubric_grading import (
    Criterion,
    Evidence,
    GradingResult,
    RubricGrader,
    build_default_grader,
)
from .semantic_consistency import (
    SemanticConsistencyResult,
    SentenceEmbeddingService,
    check_semantic_consistency,
    consistency_threshold,
    extract_code_documentation,
)
from .video_analysis import Transcriber, VideoAnalysis, analyze_video


@dataclass
class AggregatedResult:
    code_reports: list[CodeReport]
    report_analysis: ReportAnalysis | None
    video_analysis: VideoAnalysis | None
    consistency: ConsistencyResult
    grading: GradingResult
    similarity_flagged: bool
    code_ai_flagged: bool
    review_flags: list[str] = field(default_factory=list)
    # Meaning-based code-docs/report/transcript comparison; a review
    # signal only -- it never feeds the grader.
    semantic_consistency: SemanticConsistencyResult | None = None

    @property
    def recommended_score(self) -> float:
        return self.grading.total_score

    @property
    def recommended_max(self) -> float:
        return self.grading.max_total

    @property
    def needs_human_review(self) -> bool:
        return bool(self.review_flags)


def evaluate_submission(
    *,
    code_dir: Path | None = None,
    report_path: Path | None = None,
    video_path: Path | None = None,
    criteria: list[Criterion],
    grader: RubricGrader | None = None,
    transcriber: Transcriber | None = None,
    similarity_flagged: bool = False,
    semantic_review_flagged: bool = False,
    code_ai_flagged: bool = False,
    consistency_service: SentenceEmbeddingService | None = None,
    report_extraction: ReportExtraction | None = None,
) -> AggregatedResult:
    """Run the full pipeline for one submission and return one
    aggregated result, ready to hand to an instructor dashboard.

    All three inputs (code_dir, report_path, video_path) are optional
    so partial submissions -- or a self-check run before all three
    parts are ready -- still produce a usable result.
    """
    code_reports = analyze_directory(code_dir) if code_dir else []
    report_analysis, report_read_error = None, None
    if report_path:
        try:
            report_analysis = analyze_report(report_path)
        except Exception as exc:  # corrupted/unreadable document: evaluate everything else
            report_read_error = f"{exc.__class__.__name__}: {exc}"[:200]
    # Report text for the cross-modal check comes from MarkItDown (extracted
    # at upload time when available, otherwise now). The analysis above keeps
    # its own extraction, so the grader's inputs are unchanged.
    if report_path and report_extraction is None:
        report_extraction = extract_report_text(report_path)
    video_analysis = analyze_video(video_path, transcriber) if video_path else None

    video_transcript = video_analysis.transcript.text if video_analysis else ""

    consistency = check_consistency(code_reports, report_analysis, video_transcript)
    semantic_consistency = _semantic_consistency(
        code_dir, report_extraction, video_analysis, consistency_service,
        report_submitted=report_path is not None, video_submitted=video_path is not None,
    )

    report_ai_flagged = bool(report_analysis and report_analysis.ai_text.signal == "high")
    ai_content_flagged = report_ai_flagged or code_ai_flagged

    grader = grader or build_default_grader()
    evidence = Evidence(
        code_reports=code_reports,
        report=report_analysis,
        video_transcript=video_transcript,
        similarity_flagged=similarity_flagged,
        ai_content_flagged=ai_content_flagged,
    )
    grading = grader.grade(criteria, evidence)

    review_flags: list[str] = []
    if similarity_flagged:
        review_flags.append("code similarity checker flagged this submission against another student's")
    if semantic_review_flagged:
        # Review prompt only -- deliberately NOT passed to the grader as
        # a similarity flag, so it never caps a score by itself.
        review_flags.append(
            "potential similarity detected: semantic (UniXcoder) similarity to another submission is "
            "unusually high despite limited identical code -- lecturer review recommended"
        )
    if code_ai_flagged:
        review_flags.append("code AI-content heuristic signaled high likelihood")
    if report_ai_flagged:
        review_flags.append(
            f"report AI-text heuristic signaled high likelihood ({'; '.join(report_analysis.ai_text.reasons)})"
        )
    if report_analysis and report_analysis.image_check.flagged:
        review_flags.append(report_analysis.image_check.reason)
    if consistency.flagged:
        review_flags.extend(consistency.reasons)
    if video_analysis and video_analysis.frames.screen_recording_score >= 80:
        review_flags.append(
            f"video looks like a static screen recording (avg frame diff {video_analysis.frames.avg_frame_diff})"
        )
    if report_read_error:
        review_flags.append(f"the report file could not be read for report analysis ({report_read_error})")
    if semantic_consistency and semantic_consistency.status == "review_recommended":
        review_flags.append(f"cross-modal semantic consistency: {semantic_consistency.reason}")
    if code_reports and not report_path and not video_path:
        review_flags.append("only code was submitted -- report and video are still missing")

    return AggregatedResult(
        code_reports=code_reports,
        report_analysis=report_analysis,
        video_analysis=video_analysis,
        consistency=consistency,
        grading=grading,
        similarity_flagged=similarity_flagged,
        code_ai_flagged=code_ai_flagged,
        review_flags=review_flags,
        semantic_consistency=semantic_consistency,
    )


_EXTRACTION_NOTES = {
    "empty": "Report unavailable (no extractable text)",
    "failed": "Report unavailable (text extraction failed)",
    "unsupported": "Report unavailable (unsupported or invalid document)",
}


def _semantic_consistency(code_dir, report_extraction, video_analysis, service, *, report_submitted, video_submitted):
    """Uses the MarkItDown report text and the transcript the video stage
    already produced -- nothing is transcribed twice. Guarded so a failure
    in this optional stage can never break the evaluation."""
    try:
        return check_semantic_consistency(
            code_documentation=extract_code_documentation(code_dir) if code_dir else None,
            report_text=report_extraction.text if report_extraction and report_extraction.ok else None,
            report_extraction=report_extraction.meta() if report_extraction else None,
            report_unavailable_note=_EXTRACTION_NOTES.get(report_extraction.status) if report_extraction else None,
            transcript=video_analysis.transcript.text if video_analysis else None,
            code_submitted=code_dir is not None,
            report_submitted=report_submitted,
            video_submitted=video_submitted,
            transcript_backend=video_analysis.transcript.backend if video_analysis else None,
            service=service,
        )
    except Exception as exc:  # e.g. unreadable code files while extracting documentation
        return SemanticConsistencyResult(
            None, None, None, None, status="unavailable",
            reason="Cross-modal semantic analysis could not run.",
            threshold=consistency_threshold(),
            warning=f"{exc.__class__.__name__}: {exc}. The rest of the evaluation is unaffected.",
        )
