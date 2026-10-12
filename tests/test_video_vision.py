"""Vision step: sampled video frames are described by a local vision model and
the descriptions reach the grader (so a silent video is not graded blind).
Fake model / fake `post` everywhere except one live test, so no Ollama is
needed for the normal run."""

import base64

import pytest

from app.evaluator import pipeline, rubric_grading
from app.evaluator import video_analysis as va
from app.evaluator.rubric_grading import Criterion, CriterionResult, Evidence, GradingResult, RubricGrader
from app.evaluator.video_analysis import (
    FrameAnalysis,
    FrameDescription,
    FrameDescriber,
    OllamaFrameDescriber,
    TranscriptionResult,
    VideoAnalysis,
    analyze_video,
    build_default_describer,
    sample_frames,
)

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def make_video(path, frames=40, fps=10, size=(320, 240), text=None):
    """A short silent MJPG video written by OpenCV itself (no ffmpeg needed)."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for i in range(frames):
        frame = np.full((size[1], size[0], 3), (i * 6 % 256, 120, 255 - i * 6 % 256), np.uint8)
        if text:
            frame[:] = 255
            cv2.putText(frame, text, (10, size[1] // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
        writer.write(frame)
    writer.release()
    return path


class FakePost:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, payload, timeout):
        self.calls.append((url, payload))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"message": {"content": reply}}


# ---- sampling frames ------------------------------------------------------


def test_sample_frames_spreads_jpegs_across_the_video(tmp_path):
    video = make_video(tmp_path / "v.avi", frames=40, fps=10)  # 4 seconds
    frames = sample_frames(video, count=4)
    assert len(frames) == 4
    times = [t for t, _ in frames]
    assert times == sorted(times) and times[0] < 1.0 and times[-1] > 3.0   # start .. end of the video
    assert all(jpeg[:2] == b"\xff\xd8" for _, jpeg in frames)               # real JPEGs


def test_sample_frames_downscales_large_frames(tmp_path):
    video = make_video(tmp_path / "big.avi", frames=10, size=(1280, 720))
    _, jpeg = sample_frames(video, count=1, max_side=512)[0]
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert max(image.shape[:2]) <= 512


def test_sample_frames_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        sample_frames(tmp_path / "nope.avi")


# ---- the Ollama describer -------------------------------------------------


def test_describer_sends_each_frame_as_base64_to_the_vision_model():
    post = FakePost(["  A terminal showing Python code.  ", "A slide titled Bubble Sort."])
    describer = OllamaFrameDescriber(model="qwen3-vl:4b", post=post)
    out = describer.describe([(1.0, b"\xff\xd8jpeg-one"), (9.5, b"\xff\xd8jpeg-two")])

    assert [(d.seconds, d.text) for d in out] == [(1.0, "A terminal showing Python code."),
                                                  (9.5, "A slide titled Bubble Sort.")]
    assert len(post.calls) == 2                       # one call per frame
    url, payload = post.calls[0]
    assert url.endswith("/api/chat") and payload["model"] == "qwen3-vl:4b"
    assert payload["think"] is False and payload["options"]["temperature"] == 0
    assert base64.b64decode(payload["messages"][0]["images"][0]) == b"\xff\xd8jpeg-one"
    assert "do not guess" in payload["messages"][0]["content"]


def test_describer_keeps_good_frames_when_one_fails():
    post = FakePost([OSError("boom"), "A whiteboard with a diagram."])
    out = OllamaFrameDescriber(post=post).describe([(1.0, b"a"), (2.0, b"b")])
    assert [d.text for d in out] == ["A whiteboard with a diagram."]


def test_describer_raises_when_every_frame_fails():
    post = FakePost([OSError("model not found"), OSError("model not found")])
    with pytest.raises(RuntimeError, match="model not found"):
        OllamaFrameDescriber(post=post).describe([(1.0, b"a"), (2.0, b"b")])


def test_default_describer_respects_off_and_availability(monkeypatch):
    monkeypatch.setenv("VIDEO_VISION", "off")
    monkeypatch.setattr(va, "_ollama_available", lambda *a, **k: True)
    assert build_default_describer() is None                       # switched off
    monkeypatch.setenv("VIDEO_VISION", "auto")
    assert isinstance(build_default_describer(), OllamaFrameDescriber)  # installed -> used
    monkeypatch.setattr(va, "_ollama_available", lambda *a, **k: False)
    assert build_default_describer() is None                       # not installed -> skipped


# ---- analyze_video --------------------------------------------------------


class _FakeDescriber(FrameDescriber):
    model = "fake-vl"

    def describe(self, frames):
        return [FrameDescription(seconds=t, text=f"frame at {t:.0f}s") for t, _ in frames]


class _SilentTranscriber(va.Transcriber):
    def transcribe(self, video_path):
        return TranscriptionResult(text="", segments=[], backend="fake")


def test_analyze_video_attaches_frame_descriptions(tmp_path):
    video = make_video(tmp_path / "v.avi")
    result = analyze_video(video, transcriber=_SilentTranscriber(), describer=_FakeDescriber())
    assert result.transcript.text == ""                  # silent video...
    assert len(result.frame_descriptions) == 4           # ...but we know what is on screen
    assert result.vision_model == "fake-vl" and result.vision_error == ""


def test_analyze_video_survives_a_failing_vision_model(tmp_path):
    class Broken(FrameDescriber):
        model = "broken-vl"

        def describe(self, frames):
            raise RuntimeError("Ollama is down")

    video = make_video(tmp_path / "v.avi")
    result = analyze_video(video, transcriber=_SilentTranscriber(), describer=Broken())
    assert result.frame_descriptions == []
    assert "Ollama is down" in result.vision_error
    assert result.frames.frames_sampled > 0              # the rest of the analysis still ran


# ---- the grader prompt ----------------------------------------------------


def test_prompt_includes_timestamped_frame_descriptions():
    evidence = Evidence(video_frames=[(5.0, "A terminal running a sort script."),
                                      (75.0, "A slide titled Results.")])
    prompt = rubric_grading._build_prompt([Criterion("Video", max_points=5)], evidence)
    assert "VIDEO FRAMES" in prompt and "can still be judged from what is on screen" in prompt
    assert "Text shown on screen" in prompt and "counts as evidence" in prompt
    assert "[0:05] A terminal running a sort script." in prompt
    assert "[1:15] A slide titled Results." in prompt


def test_prompt_without_frames_says_so():
    prompt = rubric_grading._build_prompt([Criterion("Video", max_points=5)], Evidence())
    assert "(no frame descriptions available)" in prompt


# ---- pipeline wiring ------------------------------------------------------


class _CapturingGrader(RubricGrader):
    name = "capture"

    def __init__(self):
        self.evidence = None

    def grade(self, criteria, evidence):
        self.evidence = evidence
        return GradingResult([CriterionResult(c.name, 0.0, c.max_points, "") for c in criteria], self.name)


def _video_analysis(descriptions=(), vision_error=""):
    return VideoAnalysis(
        transcript=TranscriptionResult(text="", segments=[], backend="fake"),
        frames=FrameAnalysis(frames_sampled=5, duration_seconds=5.0, scene_changes=1,
                             avg_frame_diff=15.0, screen_recording_score=20),
        frame_descriptions=list(descriptions), vision_model="fake-vl", vision_error=vision_error,
    )


def _run(tmp_path, monkeypatch, analysis):
    monkeypatch.setattr(pipeline, "analyze_video", lambda *a, **k: analysis)
    grader = _CapturingGrader()
    result = pipeline.evaluate_submission(
        video_path=tmp_path / "v.avi", criteria=[Criterion("Video content", max_points=10)], grader=grader)
    return grader, result


def test_pipeline_gives_the_grader_the_frame_descriptions(tmp_path, monkeypatch):
    analysis = _video_analysis([FrameDescription(3.0, "A slide explaining bubble sort.")])
    grader, result = _run(tmp_path, monkeypatch, analysis)
    assert grader.evidence.video_frames == [(3.0, "A slide explaining bubble sort.")]
    assert grader.evidence.video_transcript == ""        # silent, yet the grader has evidence
    assert not any("vision model" in f for f in result.review_flags)


def test_pipeline_flags_a_failed_vision_step_and_still_grades(tmp_path, monkeypatch):
    grader, result = _run(tmp_path, monkeypatch, _video_analysis(vision_error="RuntimeError: model not found"))
    assert grader.evidence.video_frames == []
    assert any("could not be described by the vision model" in f and "model not found" in f
               for f in result.review_flags)


# ---- live (only when the vision model is installed) -----------------------


@pytest.mark.slow
def test_real_vision_model_reads_text_on_screen(tmp_path):
    if not rubric_grading._ollama_available(va.OLLAMA_URL, va.VISION_MODEL):
        pytest.skip(f"vision model {va.VISION_MODEL} not installed (ollama pull {va.VISION_MODEL})")
    video = make_video(tmp_path / "slide.avi", frames=30, size=(640, 360), text="BUBBLE SORT")
    result = analyze_video(video, transcriber=_SilentTranscriber(), describer=OllamaFrameDescriber())
    assert result.vision_error == "" and result.frame_descriptions
    assert any("bubble" in d.text.lower() for d in result.frame_descriptions)
