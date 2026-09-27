"""HTML report generation for a similarity-check run."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from .ai_heuristics import HeuristicScore
from .core import PairResult

_STYLE = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; background: #fafafa; }
h1 { margin-bottom: 0.25rem; }
.meta { color: #666; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; background: #fff; }
th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; font-size: 0.9rem; }
th { background: #f0f0f0; }
.flag-high { background: #fdecea; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.8rem; }
.badge-high { background: #fdecea; color: #b3261e; }
.badge-medium { background: #fff8e1; color: #8a6100; }
.badge-low { background: #e8f5e9; color: #1e6b2f; }
"""


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_html(pairs: list[PairResult], scores: list[HeuristicScore],
                 threshold: float = 0.6) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    pair_rows = []
    for p in pairs:
        cls = "flag-high" if p.flagged else ""
        pair_rows.append(
            f"<tr class='{cls}'><td>{escape(p.submission_a)}</td>"
            f"<td>{escape(p.submission_b)}</td>"
            f"<td>{_pct(p.jaccard)}</td><td>{_pct(p.containment)}</td>"
            f"<td>{p.shared_fingerprints}</td>"
            f"<td>{'&#9873; review' if p.flagged else ''}</td></tr>"
        )

    score_rows = []
    for s in sorted(scores, key=lambda s: s.score, reverse=True):
        score_rows.append(
            f"<tr><td>{escape(s.submission_id)}</td>"
            f"<td><span class='badge badge-{s.signal}'>{s.signal}</span></td>"
            f"<td>{s.score}</td>"
            f"<td>{escape('; '.join(s.reasons))}</td></tr>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Pre-submission self-check report</title>
<style>{_STYLE}</style></head><body>
<h1>Pre-submission self-check report</h1>
<p class="meta">Generated {generated} &middot; similarity flag threshold: Jaccard &ge; {_pct(threshold)}
or containment &ge; 75% &middot; this is a self-check signal, not a final grade.</p>

<h2>Code similarity (pairwise)</h2>
<table>
<tr><th>Submission A</th><th>Submission B</th><th>Jaccard</th><th>Containment</th>
<th>Shared fingerprints</th><th>Flag</th></tr>
{''.join(pair_rows) if pair_rows else '<tr><td colspan="6">No pairs to compare.</td></tr>'}
</table>

<h2>AI-content heuristic (experimental)</h2>
<p class="meta">Heuristic style signal only &mdash; not a validated AI-detection classifier.
Treat as a prompt for a human look, never an automatic penalty.</p>
<table>
<tr><th>Submission</th><th>Signal</th><th>Score</th><th>Contributing factors</th></tr>
{''.join(score_rows) if score_rows else '<tr><td colspan="4">No submissions scored.</td></tr>'}
</table>
</body></html>"""
