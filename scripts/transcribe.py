"""
transcribe.py — Local audio transcription using mlx-whisper on Apple Silicon.

Takes a video file, extracts audio via ffmpeg, then transcribes using
Whisper large-v3-turbo. Returns transcript with word-level timestamps.

Usage:
    python transcribe.py /path/to/video.mp4

Output:
    Writes transcript.json to same directory as video, containing:
    {
        "text": "full transcript...",
        "segments": [
            {
                "start": 0.0,
                "end": 5.2,
                "text": "Starting trade one on EURUSD..."
            },
            ...
        ],
        "words": [
            {"word": "Starting", "start": 0.0, "end": 0.3},
            {"word": "trade", "start": 0.3, "end": 0.6},
            ...
        ]
    }
"""

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("transcribe")


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """
    Extract audio from video using ffmpeg.
    Outputs 16kHz mono WAV (optimal for Whisper).
    """
    logger.info(f"Extracting audio from {video_path.name}...")

    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-ar", "16000",       # 16kHz sample rate (Whisper optimal)
        "-ac", "1",           # Mono channel
        "-vn",                # No video
        "-y",                 # Overwrite output
        str(audio_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-500:]}")

    logger.info(f"Audio extracted to {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return audio_path


def transcribe_audio(audio_path: Path) -> dict:
    """
    Transcribe audio using mlx-whisper (Apple Silicon optimized).
    Returns dict with 'text', 'segments', and 'words'.
    """
    logger.info("Loading mlx-whisper model (this may take a moment on first run)...")

    try:
        import mlx_whisper
    except ImportError:
        logger.error(
            "mlx-whisper not installed. Install with:\n"
            "  pip install mlx-whisper\n"
            "Or if using the project requirements:\n"
            "  pip install -r requirements.txt"
        )
        raise

    # Add the config import here to avoid circular imports at module level
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config.settings import WHISPER_MODEL

    logger.info(f"Transcribing with model: {WHISPER_MODEL}")
    logger.info(f"Audio file: {audio_path.name}")

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=WHISPER_MODEL,
        word_timestamps=True,
        language="en",
        verbose=False,
    )

    # Extract word-level timestamps from segments
    words = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            words.append({
                "word": word_info.get("word", "").strip(),
                "start": round(word_info.get("start", 0), 2),
                "end": round(word_info.get("end", 0), 2),
            })

    # Build clean output
    transcript = {
        "text": result.get("text", "").strip(),
        "segments": [
            {
                "start": round(seg.get("start", 0), 2),
                "end": round(seg.get("end", 0), 2),
                "text": seg.get("text", "").strip(),
            }
            for seg in result.get("segments", [])
        ],
        "words": words,
    }

    logger.info(f"Transcription complete. {len(transcript['segments'])} segments, {len(words)} words.")
    return transcript


def transcribe_video(video_path: str | Path) -> dict:
    """
    Main entry point: video file → transcript dict.
    Also saves transcript.json alongside the video.
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Extract audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = Path(tmp.name)

    try:
        extract_audio(video_path, audio_path)
        transcript = transcribe_audio(audio_path)
    finally:
        # Clean up temp audio file
        if audio_path.exists():
            audio_path.unlink()

    # Save transcript JSON alongside the video
    output_path = video_path.parent / f"{video_path.stem}_transcript.json"
    with open(output_path, "w") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    logger.info(f"Transcript saved to {output_path.name}")
    return transcript


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <video_path>")
        sys.exit(1)

    video_file = Path(sys.argv[1])
    result = transcribe_video(video_file)
    print(f"\nTranscript ({len(result['words'])} words):")
    print(result["text"][:500] + "..." if len(result["text"]) > 500 else result["text"])
