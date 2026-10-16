# Podcast Afterparty: starter kit

Built by Des Dreckett for the AI Video Motion community

Podcast Afterparty turns one recorded episode (an MP4, or a YouTube link) into a full content pack: a loudness-normalised MP3, a speaker-labelled transcript, captions, show notes with chapters, a YouTube description pack, a blog post, clip suggestions, and an episode cover and thumbnail in the client's brand. Every written draft carries an example-draft notice, and a QA script checks the whole episode folder before anything goes to the client.

This repo holds the tooling and the outlines. The bot does the writing; these tools do the audio, speakers, artwork and checks.

## Quickstart

```bash
git clone https://github.com/desdrec-source/podcast-afterparty-kit.git
cd podcast-afterparty-kit
bash setup.sh
```

A bot keeps the kit at `/workspace/podcast/kit`:

```bash
git clone https://github.com/desdrec-source/podcast-afterparty-kit.git /workspace/podcast/kit \
  || git -C /workspace/podcast/kit pull --ff-only
bash /workspace/podcast/kit/setup.sh
```

You can also use the zip: download https://github.com/desdrec-source/podcast-afterparty-kit/archive/refs/heads/main.zip, unzip it, and run `bash setup.sh`.

## Setup

Requirements: Python 3.11+ (tested on 3.13) and ffmpeg/ffprobe on PATH (with `loudnorm` and `libmp3lame`):
- macOS: `brew install ffmpeg`
- Debian/Ubuntu: `sudo apt install ffmpeg`
- Windows: `winget install ffmpeg`

`setup.sh` is a one-shot installer and is safe to run again; it skips anything already installed:
1. Checks ffmpeg, ffprobe, `loudnorm` and `libmp3lame`.
2. Transcription venv at `/workspace/.wv`: faster-whisper 1.2.1, `av<16`, and yt-dlp (unless yt-dlp is already on PATH).
3. Diarisation venv at `/workspace/.diar`: CPU-only torch 2.14.1 / torchaudio 2.11.0, speechbrain 1.1.2, scikit-learn, scipy, soundfile, python-docx, Pillow, faster-whisper.
4. Prints a smoke test of the installed versions.

Change the locations with `WV=... DIAR=... bash setup.sh`, or the interpreter with `PYTHON=...`. Everything runs on the CPU; no API keys or tokens are needed (the SpeechBrain speaker model downloads from Hugging Face on first use).

## Layout

```
setup.sh                      installer (ffmpeg checks + both venvs)
tools/normalise.sh            loudness normalisation to MP3
tools/diarise.py              token-free speaker diarisation
tools/qa_check.py             episode-folder QA (PASS/FAIL table)
templates/artwork_template.py cover 3000x3000 + YouTube thumbnail 1280x720 from a JSON brand config
templates/*.txt               outlines: Style Guide, Client Intake, Episode Index, show notes,
                              YouTube pack, blog post, clip suggestions
```

## Tools

### normalise.sh: loudness
```bash
bash tools/normalise.sh "episode.mp4" "Episode - normalised -16 LUFS.mp3"          # -16 LUFS, TP <= -1 dBTP
bash tools/normalise.sh in.wav out.mp3 -14 -1                                      # custom target I / TP
```
Measures, applies static gain plus an oversampled true-peak limiter, runs `loudnorm` in **linear** mode (falls back to dynamic only if linear is refused, and says so), encodes 48 kHz MP3 192k, then re-measures with `ebur128` and prints a before/after table with PASS/FAIL (exit code 1 on FAIL).

### diarise.py: who spoke when
```bash
/workspace/.diar/bin/python tools/diarise.py audio.mp3 transcript.json -n 2 -o out/episode
/workspace/.diar/bin/python tools/diarise.py audio.mp3 transcript.txt  -n 0 -o out/episode   # 0 = auto speaker count
```
SpeechBrain ECAPA embeddings plus agglomerative clustering, CPU only, no Hugging Face token. The transcript can be faster-whisper/whisper JSON with word timings, a flat word list, `[mm:ss] Name: text` lines, or an `.srt` (word timings are then produced with faster-whisper; pick the model with `--whisper-model small.en`). Writes `OUT.json` (words, turns, lines) and `OUT.txt` (speaker-labelled transcript). Rename `SPEAKER_1`, `SPEAKER_2` to real names only from the intake or the recording itself. Other options: `--threshold`, `--win`, `--hop`, `--min-turn` (see `-h`).

### qa_check.py: episode QA
```bash
/workspace/.diar/bin/python tools/qa_check.py "path/to/Episode folder"
/workspace/.diar/bin/python tools/qa_check.py FOLDER --lufs -16 --tol 1 --tp -1 --forbid "Name1|Name2"
```
Reads the `.docx/.md/.txt/.html/.srt` files and media in the folder and prints PASS/FAIL for:
- show-notes title under 60 characters, and an `In one sentence:` answer of 150 characters or fewer;
- chapters: start at 00:00, at least 3, ascending, at least 10 s apart;
- the example-draft notice in every written doc (required);
- the AI Video Motion footer line (`Created for AI Video Motion members`) in every written doc (required);
- optional `--forbid` regex: names that must not appear in text, file names, docx metadata or MP3 tags;
- the normalised MP3 is within the loudness spec;
- cover 3000x3000 RGB JPEG and thumbnail 1280x720;
- SRT is valid, with at most 2 lines of 42 characters per cue.

Transcripts, captions and the Style Guide are exempt from the notice and footer checks. Exit code 0 only if everything passes.

### artwork_template.py: cover and thumbnail
```bash
python3 templates/artwork_template.py --example > "Brand Kit/brand.json"   # then edit it
python3 templates/artwork_template.py "Brand Kit/brand.json" "Episode folder"
```
The config holds the show name, title, guest label, colours (background, title box, title text, glow, accent, label text), fonts (`.ttf` paths), logo, the photo and its crop box, and output file names. Paths are relative to the config file. The background is procedural and abstract; use only the client's own photos and logos, and never generate people. The script prints the photo upscale factor; above about 2 the photo may look soft, so find a larger source image.

### Text outlines
`templates/*.txt` are plain-text outlines for the bot to fill in (as Google Docs or .docx). Written drafts start with this notice, in italics:

*This is an example draft for ideas and inspiration. We don't recommend copying and pasting it as is: review it, make changes or rewrite it in your own voice before publishing.*

and end with the AI Video Motion footer (in the YouTube pack, after the copy-paste block).

## If the YouTube download is blocked: ClipGrab

If yt-dlp is blocked or fails, ask the client for the MP4 file directly. As a fallback, they can download it themselves with ClipGrab (https://clipgrab.org) and send you the file.

ClipGrab is third-party software made by libre media labs GmbH. We're not agents, affiliates or partners of ClipGrab, and we don't earn any money from recommending it. Use it at your own risk. On Windows, read each installer screen and decline any extra software it offers. Only download videos you own or have permission to use. Downloading may breach YouTube's Terms of Service, and you're responsible for copyright.

## Licence

MIT, see LICENSE.

---

Created for AI Video Motion members. Not a member yet? Join AI Video Motion.
https://tinyurl.com/AIVideoMotion
