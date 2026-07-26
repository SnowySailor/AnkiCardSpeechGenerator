# Anki Card Speech Generator

Generates Japanese TTS audio for Anki cards and writes it back into the notes over
AnkiConnect. Built for manga sentence-mining decks, where the hard part isn't the
synthesis — it's making the model read names and unusual words correctly.

The tool solves that with two layers of pronunciation control (**replacements** and
**hints**), scoped globally, per-series, per-volume, or per-page, plus a content hash so
each card's audio is only regenerated when something that affects it actually changes.

## How it works

```
Anki deck ──findCards/cardsInfo──> ProcessableCard ──> hash ──> up to date? ──> skip
                                         │                          │
                                    replacements                   no
                                       + hints                      │
                                         │                          v
                                         └──────────> Gemini TTS ──> MP3
                                                                     │
                                            storeMediaFile + updateNoteFields
```

For each card in the deck:

1. Read `Expression` and strip HTML tags. Empty sentences are skipped.
2. Collect the **replacements** that apply, and hard-substitute each matched surface
   form with its kana reading. This is the text actually sent to the TTS API.
3. Collect the **hints** that apply and build a Japanese steering prompt from them. Any
   hint whose word was already substituted away in step 2 is dropped, so a hint can
   never contradict a replacement.
4. Hash the sentence, the replacements, the hints, and the voice settings into a
   16-character digest → `speech_<hash>.mp3`.
5. If that hash isn't already in the note's `AI Audio` field (or `Regenerate Audio` is
   set), synthesize, store the media in Anki, and point `AI Audio` at the new file.

## Replacements vs. hints

Both map a written form to a reading, but they reach the model in completely different
ways. This is the central design decision in the project.

| | **Replacements** (`replacements.json`) | **Hints** (`hints.json`) |
|---|---|---|
| Mechanism | Text is rewritten before synthesis — the kanji never reaches the model | Passed as a natural-language `prompt` alongside the text |
| Reliability | Deterministic | Best-effort; the model may ignore it |
| Prosody | Can flatten pitch accent, since the model only sees kana | Preserved — the model still sees the real sentence |
| Use for | Names and readings the model reliably gets wrong (`曲` → `マガリ`) | Nudges where the default reading is merely likely-wrong (`色黒` → `いろぐろ`) |

Gemini TTS has no phoneme override, and a prompt alone can't reliably beat the model's
lexical prior (`明日` → `あす` when you need `アケビ`). Replacing the surface form with
kana removes the ambiguity entirely — at the cost of some naturalness. Reach for a hint
first; escalate to a replacement when the model won't cooperate.

Replacement substitution runs longest-original-first, so compounds are consumed before
their overlapping parts (`明日小路` before `明日` and `小路`). Readings are kana, so they
can never cascade into a later substitution.

## Scoping

`replacements.json` and `hints.json` share one format, keyed by the note's `Source`
field:

```json
{
  "*":   { "薫子": "カオルコ" },
  "INS": {
    "*":  { "曲": "マガリ" },
    "V1": {
      "*":   { "中見": "ナカミ" },
      "P11": { "眠み": "ネミ" }
    }
  }
}
```

- `*` at the top level — every card in every deck.
- `<SERIES>` → `*` — every card from that series.
- `<SERIES>` → `<VOLUME>` → `*` — every card in that volume.
- `<SERIES>` → `<VOLUME>` → `<PAGE>` — that page only.

The `Source` field is parsed as `SERIES VOLUME PAGES`, e.g. `INS V1 P11` or
`INS V1 P11,12` (which expands to `P11` and `P12`). More specific scopes override
broader ones, and a per-card field beats everything in JSON.

A pair only takes effect if its written form actually appears in the sentence, so
entries scoped broadly are harmless on cards that don't contain the word.

## Note fields

Field names are constants at the top of `processor.py`.

| Field | Required | Purpose |
|---|---|---|
| `Expression` | yes | Sentence to speak. HTML is stripped. |
| `AI Audio` | yes | Written by the tool as `[sound:speech_<hash>.mp3]`. Also read back to decide whether the audio is current. |
| `Source` | no | Scope key for replacements and hints, e.g. `INS V1 P11`. |
| `Regenerate Audio` | no | Any non-empty value forces regeneration; cleared automatically on success. |
| `Replacements` | no | Per-card hard replacements: `search:reading,search:reading`. |
| `Reading Hints` | no | Per-card soft hints, same format. |

### Configuring the fields in Anki

Add the fields to the note type you mine into — **Tools → Manage Note Types →** select the
type **→ Fields… → Add**. Names must match exactly, including capitalization and the space
in `AI Audio` and `Regenerate Audio`; the lookup is a literal dictionary hit, not a fuzzy
match. Adding fields is non-destructive, and the four optional ones can be left out
entirely — a field that doesn't exist reads as empty.

The two required ones fail in different, quiet ways if they're wrong:

- **No `Expression`** (or it's named something else) — every card reads as an empty
  sentence and is skipped. You'll see `Skipped N cards with empty sentences.` and nothing
  will be generated.
- **No `AI Audio`** — audio is synthesized, but AnkiConnect rejects the write-back and
  each card logs `ERROR updating Anki`. The run continues to the end, so this can burn a
  lot of API calls before you notice.

Run `--dry-run` first on any new note type. It catches an `Expression` mismatch for free —
the skip count will equal the card count and you'll get `0 need audio generation` — but it
can't catch an `AI Audio` mismatch, since it never reaches the write-back. Confirm that
field name by eye.

Then reference the field in your card template (**Cards…**) so the audio actually plays
during review:

```
{{Expression}}
{{AI Audio}}
```

Leave `AI Audio` for the tool to manage — each run overwrites the whole field value, so
anything else you put there is lost. If you already keep audio from another source, give
this a separate field rather than sharing one.

To use your existing field names instead of these, edit the constants at the top of
`processor.py`. Only field *values* are hashed, never their names, so renaming is free —
no rehash, no mass regeneration.

### Filling in the optional fields

`Source` is what makes scoped replacements work — without it, only the top-level `*`
entries apply. Format it as `SERIES VOLUME PAGES`, e.g. `INS V1 P11,12`.

`Regenerate Audio` takes any non-empty value (`1`, `y`, `x` — nothing parses it), and the
tool clears it once the card succeeds, so it works as a one-shot checkbox you can set on a
batch of cards from the browser.

`Replacements` and `Reading Hints` both take `written:reading` pairs separated by commas —
`曲:マガリ,兎子:ウサコ`. Items without a colon are ignored, and whitespace around the
commas and colons is stripped. Use these for one-off cards; anything recurring belongs in
the JSON files so it applies everywhere.

### One caveat on deck selection

Cards are found with `deck:"<name>"`, and the tool works per *card*, not per *note*. If
your note type produces more than one card per note, each note is synthesized once per
card — same sentence, same hash, same output filename, so the result is correct, but you
pay for the duplicate TTS calls. Mining decks are usually one card per note; if yours
isn't, be aware the card count in the output is higher than the number of distinct
sentences.

## Setup

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
brew install ffmpeg          # pydub needs it for MP3 export
```

**Google Cloud Text-to-Speech.** Audio comes from the Gemini TTS model
(`gemini-3.1-flash-tts-preview`) via the Cloud TTS API, which authenticates with
Application Default Credentials — not an API key:

```bash
gcloud auth application-default login
gcloud services enable texttospeech.googleapis.com
```

**AnkiConnect.** Install add-on `2055492159` (Tools → Add-ons → Get Add-ons), restart
Anki, and verify:

```bash
curl http://localhost:8765 -X POST -d '{"action": "version", "version": 6}'
# {"result": 6, "error": null}
```

Anki must be running whenever the tool is used.

## Usage

```bash
# See what would be generated, without calling the TTS API
python main.py "Mining" --dry-run

# Generate and write back
python main.py "Mining"
```

There are no other flags. To force a rebuild of one card, set its `Regenerate Audio`
field; to force a rebuild of everything, bump `HASH_VERSION` in `hasher.py`.

Every generated file is written twice: into Anki's media collection via `storeMediaFile`,
and into a local `audio_output/` cache in the project root (git-ignored). The local copy
isn't read back — regeneration is decided from the note's `AI Audio` field — so it's safe
to delete if it gets large.

## Layout

| File | Role |
|---|---|
| `main.py` | CLI entry point; wires up the client, generator, and processor |
| `processor.py` | Builds `ProcessableCard`s, decides what needs audio, drives generation and write-back |
| `anki.py` | `AnkiClient` — AnkiConnect JSON-RPC, with `cardsInfo` batched 500 at a time |
| `replacements.py` | Loading, `Source` parsing, scope resolution, substitution, prompt building |
| `hasher.py` | Content hash that decides staleness |
| `audio/base.py` | `AudioGenerator` ABC: `generate(text, prompt) -> bytes` |
| `audio/gemini.py` | Cloud TTS implementation; LINEAR16 24 kHz → WAV → MP3 128k via pydub |
| `replacements.json` | Hard replacement data |
| `hints.json` | Soft hint data |

Voice and encoding settings (`Kore`, `128k`, speed `1.0`) are duplicated in
`audio/gemini.py` and `hasher.py` — the generator uses them, the hasher folds them into
the digest. **Change them in both places**, otherwise existing cards keep their old audio
because the hash doesn't move.

## Adding a TTS provider

Subclass `AudioGenerator`, implement `generate(text, prompt) -> bytes` returning MP3,
and construct it in `main.py`. Update `PROVIDER` in `hasher.py` so that switching
providers invalidates the existing audio.
