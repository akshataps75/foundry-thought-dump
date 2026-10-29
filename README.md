# Thought Dump

A small local tool for getting a thought out of your head in a few seconds and finding it again later. Built on [Microsoft Foundry Local](https://learn.microsoft.com/azure/ai-foundry/foundry-local/) so the one AI feature runs on the laptop, with nothing sent to the cloud.

## Why I built it

When I'm in the middle of a task, a stray thought pulls me away: a new concept I want to look up, an idea, "I forgot to dry my clothes". Searching it right then turns a short task into a detour, and trusting myself to remember later doesn't work. I wanted one place to drop the thought and keep going.

Tools like it exist. I built it because I had a specific set of constraints that were easier to guarantee in my own code, and because I wanted to learn where a local model belongs in a workflow, and where it doesn't.

## Constraints I set

| Constraint | How it is met |
|---|---|
| Never auto-starts with Windows | Nothing is installed as a startup item. Every run starts when I type `dump` and ends when I close it. |
| No popups or notifications (online tests, interviews) | No tray icon, no hotkey listener, no background process. A window opens only when I run `dump`. |
| Capture must be instant | Saving a thought writes one row to a local SQLite file. The model is never involved. |
| Private | Everything is stored in a local file. The model runs on the laptop. No internet is needed after the model has been downloaded. |

## What it does

Run `dump` to open the window. Thoughts live in six tabs:

- **Tasks**: tick to cross out. **Refresh Done** moves ticked tasks to the Archive.
- **Ideas**, **On my mind**: multi-select, then **Archive Selected**.
- **Unlabelled**: thoughts saved without a label, with per-row buttons to sort them into Task, Idea or On my mind.
- **Archive**: archived items wait 30 days, then are deleted for good. **Restore Selected** brings them back.
- **Search**: keyword search, with an optional "Also try related words" checkbox.

A **Back up** button copies the database to a folder you choose.

The command line works too:

```
dump                              open the window
dump "text"                       save a thought (unlabelled)
dump "text" --task                save as a task (also --idea, --mind)
dump -f words                     search
dump -f words --expand            search, then add related words from the local model
dump --help
```

## How it works

**Storage.** One SQLite file, `thoughts.db`, next to `thought.py`. A `thoughts` table (`id, text, created, label, status, state, state_changed`) plus an FTS5 full-text index kept in sync by triggers. The schema is created on first run.

**Search.** The query is split into words, filler words ("what", "if", "about") are dropped, and each remaining word matches as a prefix (so `sched` finds `scheduling`). Any word may match, and results are ranked with `bm25`.

**Related-words search (the only place the model is used).**

1. Plain search runs first and its results show immediately.
2. If the box is ticked, the app loads `qwen2.5-1.5b` through the Foundry Local Python SDK in a background thread.
3. A few-shot prompt asks for up to 8 related words on one line.
4. The reply is cleaned (lowercase, 3+ letters, no filler, nothing already searched), and those words are searched again. Results already shown are skipped.
5. The model is unloaded in a `finally` block, so it is out of memory whether the call worked or not.

If the model is missing or fails, a message appears and the plain results still stand.

## Design decisions and trade-offs

- **A window I open, not a hotkey popup.** Hotkey tools run in the background and listen system-wide, which is exactly what I don't want near a proctored test. The cost is one extra step to open the window.
- **I label thoughts myself instead of letting the model guess.** In a real run, the model's suggested label matched mine in only 3 of 6 thoughts. And labels are optional at capture time so saving stays instant.
- **The model is off unless I ask for it.** It is loaded for each related-words search and unloaded after, so it doesn't sit in memory or heat the laptop. The cost is a load delay on every expanded search (measured below).
- **Archive instead of delete.** Like a phone gallery's recently-deleted folder: if I change my mind, I can restore it. Items are purged after 30 days because I don't want to keep collecting things.
- **"On my mind" instead of "worry".** I first used "worry", but the label itself felt heavy.
- **Cut on purpose:** calendar and reminders (my phone covers them), embeddings and question-answering over notes (I kept the scope to dump and find), a daily checklist (it doesn't fit how I work), and a hotkey popup.

## Models I tried

These tests were for the labeling idea I later dropped, run on 12 short notes. They are a rough check, not a benchmark.

| Model | Correct, plain instruction | Correct, with 4 examples in the prompt | Time per note |
|---|---|---|---|
| qwen2.5-0.5b | 7 / 12 | 3 / 12 | 0.6 to 1.1 s |
| qwen2.5-1.5b | 5 / 12 | 8 / 12 | 1.6 to 2.9 s |
| phi-4-mini | 6 / 12 | not retested | 2.1 to 2.6 s |

What I took from it:

- Prompt design mattered more than model size. Examples helped the 1.5B model and hurt the 0.5B one, which stopped following the one-word instruction.
- CPU use rose with model size (roughly 50%, 60%, and 70 to 80%).
- The larger phi-4-mini was not better in the first round. I didn't retest it with examples, so I can't say how it compares to qwen2.5-1.5b with examples.
- The GPU build of qwen2.5-0.5b (a TensorRT-RTX variant) downloaded but failed with an internal runtime error on my laptop. The CPU build worked. I did not find the cause.
- `qwen2.5-3b` appears in the Foundry CLI list but not in the SDK catalog.

I use `qwen2.5-1.5b` for related words. The scripts for these runs are in `testing_setup/`.

## Does "related words" actually help?

`testing_setup/eval_expand.py` runs a set of queries against a throwaway database, once with plain search and once with related words added, and compares both against answers I wrote by hand.

| | Plain search | With related words |
|---|---|---|
| Relevant thoughts found | 5 / 15 | 6 / 15 |
| Irrelevant results returned | 1 | 4 |
| Queries where related words found something plain missed | | 1 |
| Queries where related words only added noise | | 3 |
| Average time for related words (load + answer + unload) | | 24.4 s |

**Notes on this test:** 12 queries over 16 thoughts; “relevant” is my own judgement, and I wrote the starter set. Related words recovered one extra thought (“tired at night” found “can’t sleep”), added three irrelevant results, and took about 24 s per search because the model is loaded and unloaded each time (7.6 to 30.7 s). In this test it did not earn a place as a default, so it stays an opt-in checkbox

## Setup

Tested on Windows 11 (i5-12450H, 16 GB RAM, RTX 3050 Laptop GPU, no NPU), Python 3.12, Foundry Local CLI 0.12.1.

```
git clone https://github.com/akshataps75/foundry-thought-dump
cd foundry-thought-dump
python -m venv .venv
.venv\Scripts\pip install foundry-local-sdk-winml
dump.bat
```

Saving, labelling, archiving and plain search work without Foundry. Only "related words" needs it:

```
winget install Microsoft.FoundryLocal
```

The model downloads the first time you use related words. Optionally add the folder to your `PATH` so `dump` works from anywhere.

## Limitations

- **Plain search matches word beginnings only.** `ideas` will not find `idea`, and `nervous` will not find `worried` unless related words are on.
- **Related-words quality is limited by a 1.5B model**, and prefix matching can pull in unrelated words (`work` also matches `network`).
- **The database is plain, unencrypted text.** It stays on your machine, but anyone with access to the file can read it. Don't dump passwords.
- **Archive purge is permanent** after 30 days.
- **Bare words typed after `dump` are saved as a thought**, so `dump l` once saved the letter "l".
- **Tested only on one Windows laptop.** I have not tested it on weaker machines, other operating systems, or very large databases.

## Ideas I haven't tried

- Letting a local model look for patterns across what I dump. Untested, and a small model may give shallow readings of personal notes.
- Checking how it runs on lower-end laptops.

## Files

| File | What it is |
|---|---|
| `thought.py` | The whole tool: database, search, window, command line. |
| `dump.bat` | Launcher. Uses `.venv` next to it if it exists, otherwise your system Python. |
| `testing_setup/hello_foundry.py` | First test: one model, one question. |
| `testing_setup/compare_models.py` | The 12-note labeling experiment (currently lists only `qwen2.5-1.5b`). |
| `testing_setup/eval_expand.py` | Plain search versus related-words search. |