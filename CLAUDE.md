# Gita Samagam

## Project Purpose

Convert Gita Samagam Hindi lecture recordings (Acharya Prashant) into study flashcards.

Pipeline: **m3u8 URL → mp3 → Hindi transcript → Markdown flashcards**

## How to Run

```bash
# Activate venv (sarvamai lives here)
source .venv/bin/activate

# Run pipeline (download + transcribe)
python pipeline.py "<m3u8_url>"

# Example
python pipeline.py "https://video1.acharyaprashant.org/courses/2023-08-12/2023-05-08-gita-samagam-hindi-part1-2ff7932/playlist.m3u8"
```

Pipeline is idempotent — skips download if `.mp3` exists, skips transcription if `.txt` exists.

## Flashcard Generation (Manual Step)

After the pipeline produces a `.txt` transcript, ask Claude Code to generate flashcards from it. The flashcard format lives in `/Users/ash-19027/claudecode/AI Obsidian/CLAUDE.md`. Key rules:

- Hindi Q&A cards, `## Question\n---\nAnswer\n===` format
- ~3-10 cards per hour of content
- Atomic: one idea per card
- Focus on spiritual/philosophical insights, mental models, decision principles
- Save as `<same-stem>.md` alongside the transcript

## File Structure

| File | Purpose |
|------|---------|
| `pipeline.py` | Main script — download (ffmpeg) + transcribe (Sarvam AI) |
| `.env` | `SARVAM_API_KEY` (auto-loaded by pipeline) |
| `.venv/` | Python venv with `sarvamai` package |
| `requirements.txt` | `sarvamai` dependency |
| `*.mp3` | Downloaded audio files |
| `*.txt` | Hindi transcripts from Sarvam AI |
| `*.md` | Flashcards (generated separately) |

## URL Pattern

Source videos are HLS streams from Acharya Prashant's platform:
```
https://video1.acharyaprashant.org/courses/<course-date>/<lecture-date>-gita-samagam-hindi-part<N>-<hash>/playlist.m3u8
```

The pipeline strips the hash suffix to derive clean filenames like `2023-05-08-gita-samagam-hindi-part1`.

## Sarvam AI Details

- **Package**: `sarvamai` (v0.1.26, installed in .venv)
- **API**: Batch Speech-to-Text (`client.speech_to_text_job`)
- **Model**: `saaras:v3`, mode: `transcribe`, language: `hi-IN`
- **Limit**: 60 min per file, 20 files per job
- **Chunking**: Audio >60 min auto-splits at 55-min marks, chunks uploaded as single batch job, transcripts concatenated
- **Cost**: ~Rs 30/hour of audio. Free tier: Rs 1,000 credits (~33 lectures)
- **Flow**: `create_job()` → `upload_files()` → `start()` → `wait_until_complete()` → `download_outputs()`

## Dependencies

- Python 3.8+ (currently 3.14)
- `ffmpeg` + `ffprobe` (installed via brew)
- `sarvamai` Python package (in .venv)

## What Worked

- ffmpeg HLS-to-mp3 extraction with `-vn -acodec libmp3lame -q:a 2`
- Sarvam Batch API handles full lectures reliably
- Auto-chunking for >60 min audio (tested with 94-min file → 2 chunks)
- `download_outputs()` produces text files that can be plain text or JSON; pipeline handles both formats
- Filename derivation from URL path with hex-hash stripping

## Known Issues / Notes

- `sarvamai` emits a Pydantic v1 warning on Python 3.14 — harmless, doesn't affect functionality
- The `.mp4` file for `2023-04-21` was downloaded manually before the pipeline existed (495 MB) — pipeline only downloads mp3 (much smaller, ~50-60 MB)
- First two transcripts (`2023-04-21`, `2023-04-30`) were created before the pipeline, using the same Sarvam API manually
