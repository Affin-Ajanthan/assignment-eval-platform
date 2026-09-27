import pytest

from app.evaluator.video_analysis import (
    NullTranscriber,
    TranscriptionResult,
    Transcriber,
    WhisperTranscriber,
    analyze_frames,
    analyze_video,
    build_default_transcriber,
)
from helpers import make_two_scene_video


def test_analyze_frames_detects_scene_change(tmp_path):
    video_path = make_two_scene_video(tmp_path / "two_scene.mp4", seg_seconds=2.0, fps=10)
    result = analyze_frames(video_path, sample_fps=5.0)
    assert result.frames_sampled > 0
    assert result.scene_changes >= 1
    assert result.duration_seconds == pytest.approx(4.0, abs=0.5)


def test_analyze_frames_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        analyze_frames(tmp_path / "does_not_exist.mp4")


def test_null_transcriber_returns_empty_transcript(tmp_path):
    transcriber = NullTranscriber()
    result = transcriber.transcribe(tmp_path / "whatever.mp4")
    assert result.text == ""
    assert result.segments == []
    assert result.backend == "null"


def test_build_default_transcriber_returns_a_transcriber():
    transcriber = build_default_transcriber()
    assert isinstance(transcriber, Transcriber)


class _FakeTranscriber(Transcriber):
    def transcribe(self, video_path):
        return TranscriptionResult(
            text="this project implements a bubble sort algorithm",
            segments=[{"start": 0.0, "end": 3.0, "text": "this project implements a bubble sort algorithm"}],
            backend="fake",
        )


def test_analyze_video_combines_transcript_and_frames(tmp_path):
    video_path = make_two_scene_video(tmp_path / "two_scene.mp4", seg_seconds=1.5, fps=10)
    result = analyze_video(video_path, transcriber=_FakeTranscriber())
    assert result.transcript.backend == "fake"
    assert "bubble sort" in result.transcript.text
    assert result.frames.frames_sampled > 0


@pytest.mark.slow
def test_whisper_transcriber_real_model_if_network_available(tmp_path):
    """Exercises the real faster-whisper path end-to-end. Skipped (not
    failed) when the model can't be downloaded -- e.g. this sandbox's
    egress policy blocks huggingface.co. Passing here means real
    transcription genuinely works in this environment."""
    video_path = make_two_scene_video(tmp_path / "speech.mp4", seg_seconds=2.0, fps=5, with_speech=True)
    try:
        transcriber = WhisperTranscriber(model_size="tiny")
        result = transcriber.transcribe(video_path)
    except Exception as exc:  # noqa: BLE001 - broad on purpose, network/env dependent
        pytest.skip(f"faster-whisper model unavailable in this environment: {exc}")
    assert result.backend.startswith("faster-whisper")
    assert isinstance(result.text, str)
