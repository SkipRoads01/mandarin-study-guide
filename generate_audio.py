#!/usr/bin/env python3
"""
generate_audio.py — pre-render one MP3 clip per vocabulary word for the
Guided Learn Path in index.html.

The Learn Path's ♪ Listen button looks up a card by its Chinese characters
(the vocab `char`) in audio/vocab/manifest.json. This script:

  1. Parses every *_VOCAB array out of index.html.
  2. Calls a text-to-speech API once per unique word (skipping any already
     rendered), saving audio/vocab/<hash>.mp3.
  3. Writes audio/vocab/manifest.json mapping  char -> "audio/vocab/<hash>.mp3".

Until you run this, the Learn Path just falls back to the browser's built-in
speech synthesis — so the site works either way; this only upgrades the audio.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------
  export ELEVENLABS_API_KEY="sk_..."          # required
  # optional overrides:
  export ELEVENLABS_VOICE_ID="<voice id>"     # a voice that speaks Mandarin
  export ELEVENLABS_MODEL="eleven_multilingual_v2"

  python3 generate_audio.py                   # render everything missing
  python3 generate_audio.py --dry-run         # just list what would render
  python3 generate_audio.py --force           # re-render even if file exists

The default provider is ElevenLabs (chosen for tone-accurate Mandarin). To use
a different TTS service, replace `synthesize()` — everything else is provider
agnostic. IMPORTANT for a tonal language: spot-check a few clips by ear; a
wrong tone teaches a different word.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.html")
OUT_DIR = os.path.join(ROOT, "audio", "vocab")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

# ElevenLabs "Rachel" is English-only; this default is a multilingual voice.
# Override with ELEVENLABS_VOICE_ID if you prefer another.
DEFAULT_VOICE = "pFZP5JQG7iQjIQuC4Bku"        # "Lily" (multilingual)
DEFAULT_MODEL = "eleven_multilingual_v2"


def extract_vocab(html):
    """Return a de-duplicated list of (char, pinyin) from every *_VOCAB array."""
    words = {}
    for block in re.finditer(r"_VOCAB\s*=\s*\[(.*?)\n\];", html, re.S):
        for m in re.finditer(r'\[\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"[^"]*"\s*\]', block.group(1)):
            pinyin, char = m.group(1), m.group(2)
            if char and char not in words:
                words[char] = pinyin
    return list(words.items())


def clip_name(char):
    return hashlib.md5(char.encode("utf-8")).hexdigest()[:12] + ".mp3"


def synthesize(text, api_key, voice_id, model):
    """Call ElevenLabs TTS; return MP3 bytes. Raises on HTTP error."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main():
    ap = argparse.ArgumentParser(description="Render vocab audio for the Learn Path.")
    ap.add_argument("--dry-run", action="store_true", help="list missing clips, don't call the API")
    ap.add_argument("--force", action="store_true", help="re-render clips that already exist")
    args = ap.parse_args()

    with open(INDEX, encoding="utf-8") as f:
        vocab = extract_vocab(f.read())
    print(f"Found {len(vocab)} unique vocabulary words in index.html.")

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)

    todo = []
    for char, pinyin in vocab:
        fname = clip_name(char)
        rel = f"audio/vocab/{fname}"
        manifest[char] = rel                      # ensure every word is mapped
        if args.force or not os.path.exists(os.path.join(ROOT, rel)):
            todo.append((char, pinyin, fname))

    print(f"{len(todo)} clip(s) need rendering"
          + (" (--force)" if args.force else "")
          + (" — dry run, nothing will be written." if args.dry_run else "."))

    if args.dry_run:
        for char, pinyin, _ in todo:
            print(f"  {char}  ({pinyin})")
        # Still refresh the manifest so mappings are complete.
        _write_manifest(manifest)
        return

    if todo:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            sys.exit("ERROR: set ELEVENLABS_API_KEY to render audio "
                     "(or use --dry-run). See the header of this file.")
        voice = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE)
        model = os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL)

        for i, (char, pinyin, fname) in enumerate(todo, 1):
            try:
                audio = synthesize(char, api_key, voice, model)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                sys.exit(f"\nTTS failed on {char!r} (HTTP {e.code}): {body}\n"
                         f"Manifest not fully written — fix the error and re-run.")
            rel = f"audio/vocab/{fname}"
            with open(os.path.join(ROOT, rel), "wb") as out:
                out.write(audio)
            print(f"  [{i}/{len(todo)}] {char}  ({pinyin})  ->  {rel}")
            time.sleep(0.3)                        # gentle on rate limits

    _write_manifest(manifest)
    print(f"\nDone. Wrote {MANIFEST} with {len(manifest)} entries.")
    print("Reload the site and open Learn Path — cards now use the recordings.")


def _write_manifest(manifest):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
