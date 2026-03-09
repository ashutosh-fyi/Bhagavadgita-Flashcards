#!/Users/ash-19027/claudecode/gita-samagam/.venv/bin/python
"""
Gita Samagam Pipeline
=====================
m3u8 URL → mp3 download → Hindi transcription (Sarvam AI)

Usage:
    python pipeline.py "https://video1.acharyaprashant.org/.../playlist.m3u8"
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SARVAM_MODEL = "saaras:v3"
SARVAM_MODE = "transcribe"
SARVAM_LANG = "hi-IN"
MAX_CHUNK_MINUTES = 55  # split threshold (batch API limit is 60 min)
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run(cmd: list[str], *, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess command with nice error handling."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=True, text=True, **kwargs)


def derive_stem(url: str) -> str:
    """Derive a filename stem from the m3u8 URL path.

    e.g. .../2023-04-30-gita-samagam-hindi-part1-83c3761/playlist.m3u8
      → 2023-04-30-gita-samagam-hindi-part1
    """
    parts = urlparse(url).path.rstrip("/").split("/")
    # Walk backwards to find the directory name (skip 'playlist.m3u8' etc.)
    for part in reversed(parts):
        if part.endswith(".m3u8"):
            continue
        stem = part
        break
    else:
        stem = "audio"
    # Strip trailing hash suffix like -83c3761
    tokens = stem.split("-")
    if len(tokens) > 1 and len(tokens[-1]) >= 6 and tokens[-1].isalnum():
        # Looks like a hash suffix — only strip if it's short hex-ish
        try:
            int(tokens[-1], 16)
            stem = "-".join(tokens[:-1])
        except ValueError:
            pass
    return stem


def get_duration_seconds(path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = run([
        FFPROBE, "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def split_audio(mp3_path: str, chunk_minutes: int = MAX_CHUNK_MINUTES) -> list[str]:
    """Split an mp3 into chunks of chunk_minutes length. Returns list of chunk paths."""
    duration = get_duration_seconds(mp3_path)
    chunk_secs = chunk_minutes * 60
    if duration <= chunk_secs + 30:  # small grace period
        return [mp3_path]

    stem = Path(mp3_path).stem
    parent = Path(mp3_path).parent
    chunk_dir = parent / f".chunks-{stem}"
    chunk_dir.mkdir(exist_ok=True)

    chunks = []
    start = 0
    idx = 0
    while start < duration:
        chunk_path = str(chunk_dir / f"{stem}-chunk{idx:02d}.mp3")
        cmd = [
            FFMPEG, "-y", "-i", str(mp3_path),
            "-ss", str(start), "-t", str(chunk_secs),
            "-acodec", "copy", chunk_path,
        ]
        run(cmd)
        chunks.append(chunk_path)
        start += chunk_secs
        idx += 1

    print(f"  Split into {len(chunks)} chunks ({chunk_minutes} min each)")
    return chunks


# ---------------------------------------------------------------------------
# Step 1: Download
# ---------------------------------------------------------------------------
def download(url: str, mp3_path: str) -> str:
    """Download HLS stream to mp3 using ffmpeg."""
    if os.path.exists(mp3_path):
        size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
        print(f"  SKIP: {mp3_path} already exists ({size_mb:.1f} MB)")
        return mp3_path

    print(f"  Downloading → {mp3_path}")
    cmd = [
        FFMPEG, "-y", "-loglevel", "quiet", "-stats",
        "-i", url,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        mp3_path,
    ]
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
    print(f"  Done: {size_mb:.1f} MB")
    return mp3_path


# ---------------------------------------------------------------------------
# Step 2: Transcribe
# ---------------------------------------------------------------------------
def transcribe(mp3_path: str, txt_path: str) -> str:
    """Transcribe mp3 using Sarvam Batch API. Returns path to transcript."""
    if os.path.exists(txt_path):
        size_kb = os.path.getsize(txt_path) / 1024
        print(f"  SKIP: {txt_path} already exists ({size_kb:.1f} KB)")
        return txt_path

    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        # Try loading from .env file
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
            api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        print("  ERROR: Set SARVAM_API_KEY environment variable")
        print("  Get your key at https://dashboard.sarvam.ai")
        sys.exit(1)

    from sarvamai import SarvamAI
    client = SarvamAI(api_subscription_key=api_key)

    # Check if we need to split
    duration = get_duration_seconds(mp3_path)
    duration_min = duration / 60
    print(f"  Audio duration: {duration_min:.1f} min")

    audio_files = split_audio(mp3_path) if duration_min > MAX_CHUNK_MINUTES else [mp3_path]
    is_chunked = len(audio_files) > 1

    # Create batch job
    print(f"  Creating Sarvam batch job (model={SARVAM_MODEL}, lang={SARVAM_LANG})...")
    job = client.speech_to_text_job.create_job(
        model=SARVAM_MODEL,
        mode=SARVAM_MODE,
        language_code=SARVAM_LANG,
    )

    # Upload files
    print(f"  Uploading {len(audio_files)} file(s)...")
    job.upload_files(file_paths=audio_files)

    # Start and poll with progress
    print("  Starting transcription...")
    job.start()
    start_time = time.time()
    while True:
        status = job.get_status()
        state = status.job_state
        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        total = status.total_files or len(audio_files)
        done = (status.successful_files_count or 0) + (status.failed_files_count or 0)
        print(f"\r  [{mins}:{secs:02d}] {state} — {done}/{total} files done", end="", flush=True)
        if state in ("Completed", "completed", "Failed", "failed"):
            print()  # newline after carriage-return progress
            break
        time.sleep(5)
    if state in ("Failed", "failed"):
        print(f"  ERROR: Transcription job failed")
        sys.exit(1)
    print("  Transcription complete!")

    # Download results to a temp dir, then extract transcript
    with tempfile.TemporaryDirectory() as tmpdir:
        job.download_outputs(output_dir=tmpdir)

        # Collect transcript text from output files
        transcript_parts = []
        output_files = sorted(Path(tmpdir).rglob("*"))
        for f in output_files:
            if f.is_file():
                content = f.read_text(encoding="utf-8", errors="replace")
                # Try parsing as JSON (Sarvam may output JSON with transcript field)
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and "transcript" in data:
                        transcript_parts.append(data["transcript"])
                    elif isinstance(data, list):
                        # List of segments
                        for seg in data:
                            if isinstance(seg, dict) and "transcript" in seg:
                                transcript_parts.append(seg["transcript"])
                    else:
                        transcript_parts.append(content)
                except (json.JSONDecodeError, KeyError):
                    # Plain text output
                    if content.strip():
                        transcript_parts.append(content.strip())

    transcript = "\n".join(transcript_parts)

    # Clean up chunk files
    if is_chunked:
        chunk_dir = Path(audio_files[0]).parent
        shutil.rmtree(chunk_dir, ignore_errors=True)
        print(f"  Cleaned up chunk files")

    # Save transcript
    Path(txt_path).write_text(transcript, encoding="utf-8")
    size_kb = len(transcript.encode("utf-8")) / 1024
    print(f"  Saved: {txt_path} ({size_kb:.1f} KB)")
    return txt_path


# ---------------------------------------------------------------------------
# Step 3: Summary
# ---------------------------------------------------------------------------
def print_summary(mp3_path: str, txt_path: str):
    """Print pipeline summary."""
    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print("=" * 60)

    mp3_size = os.path.getsize(mp3_path) / (1024 * 1024)
    print(f"  Audio: {mp3_path} ({mp3_size:.1f} MB)")

    duration = get_duration_seconds(mp3_path)
    mins, secs = divmod(int(duration), 60)
    print(f"  Duration: {mins}:{secs:02d}")

    txt_size = os.path.getsize(txt_path) / 1024
    txt_content = Path(txt_path).read_text(encoding="utf-8")
    word_count = len(txt_content.split())
    print(f"  Transcript: {txt_path} ({txt_size:.1f} KB, ~{word_count} words)")

    print(f"\nNext step: ask Claude Code to generate flashcards from {txt_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <m3u8_url>")
        print('  e.g.: python pipeline.py "https://video1.acharyaprashant.org/.../playlist.m3u8"')
        sys.exit(1)

    url = sys.argv[1]
    stem = derive_stem(url)
    base_dir = Path(__file__).parent

    mp3_path = str(base_dir / f"{stem}.mp3")
    txt_path = str(base_dir / f"{stem}.txt")

    print(f"Gita Samagam Pipeline")
    print(f"  URL:  {url}")
    print(f"  Stem: {stem}")
    print()

    # Step 1: Download
    print("[1/2] Download")
    download(url, mp3_path)
    print()

    # Step 2: Transcribe
    print("[2/2] Transcribe")
    transcribe(mp3_path, txt_path)

    # Summary
    print_summary(mp3_path, txt_path)


if __name__ == "__main__":
    main()
