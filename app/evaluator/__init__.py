"""
Multi-modal evaluator for the AI-Assisted Assignment Evaluation Platform.

Implements the remaining pieces of the platform plan beyond Phase 1
(the portal, ``app/main.py``) and the Phase 2 code-similarity checker
(``app/similarity/``):

- ``report_analysis`` -- extract text/images from a PDF or DOCX report,
  score it for AI-generated-text style signals (Phase 2).
- ``code_analysis`` -- static analysis of submitted code (Phase 2/3).
- ``rubric_grading`` -- score code + report evidence against an
  instructor rubric, either heuristically (offline, default) or via an
  LLM when ``ANTHROPIC_API_KEY`` is configured (Phase 3).
- ``video_analysis`` -- transcribe a presentation video and analyze its
  frames for scene changes / screen-recording likelihood (Phase 4).
- ``cross_modal`` -- check whether the code, report and video all
  describe the same actual application (Phase 5), by vocabulary overlap.
- ``semantic_consistency`` -- the same question by meaning: compares
  code documentation, report and transcript with a local
  sentence-embedding model (a review signal only).
- ``pipeline`` -- ties every stage together into one aggregated grade
  with review flags, mirroring the plan's pipeline diagram.

Every stage that would need a paid API or a downloaded ML model (LLM
grading, real speech-to-text) ships with a working, fully offline
default and a clean interface to swap in the real thing -- see each
module's docstring and the top-level README for details.
"""
