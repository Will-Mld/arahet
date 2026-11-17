# codewalk (arahet™)

Narrated, interruptible walks through code and diagrams.

Its other name is **arahet™**, from the Armenian արահետ, a footpath or trail. This repository is
`github.com/Will-Mld/arahet`; the commands and files still use the working name codewalk.

A walk is a script of short phrases. Each phrase is spoken aloud and shows the code it talks about or the part
of a schema it names; IntelliJ IDEA can follow along. You can pause, ask a question at the current place, or stop
and discuss. The walk is then amended into a new version and continues where you were.

What it does:

- **Pluggable script creator.** A coding agent writes the walk from a prompt that sets its purpose, depth, order
  and presentation, with rules against the typical errors of agent-written walks attached:
  [prompts/create-walk.md](prompts/create-walk.md), [prompts/accuracy-addendum.md](prompts/accuracy-addendum.md).
- **Pluggable script reviewer.** A review guide any model can run before anyone listens:
  [prompts/review-walk.md](prompts/review-walk.md).
- **REPL-style editing.** Play, ask, stop and discuss, amend, validate, reload and continue without losing your
  place. Every amend is a new version with its parent and a change log; corrected phrases you already heard can be
  replayed first: [prompts/discuss-and-amend.md](prompts/discuss-and-amend.md).
- **Diagrams that are checked.** PlantUML schemas whose named parts are checked against the drawing and framed
  while they are spoken about.
- **Code that moves.** Every code pointer carries an anchor; `codewalk.py validate` reports the pointers that no
  longer match the code.
- **Integration.** An MCP server for Claude Code and Codex, IntelliJ IDEA following the code, a command line for
  scripts; walks are plain files you keep in git.
- **It shows itself.** `run guide` lets the player explain itself; `run design` walks through codewalk's own code.

Planned: required diagrams named in the request and checked, re-pointing after the code changed, walks of a change,
and a demo that runs these features by itself.

## Quick start

```
git clone https://github.com/Will-Mld/arahet.git && cd arahet
```

Then let your coding agent set it up with you. Open Codex, Claude Code or GitHub Copilot in this folder and type:

> Read README-r.md and set codewalk up with me.

The agent follows [README-r.md](README-r.md): it checks your machine, offers two example projects to download, helps you with
the Azure Speech key, optionally connects IntelliJ IDEA, offers to narrate the walk and starts the player (or lets
each phrase be narrated when it first plays). It asks before
anything that downloads or changes your setup, and it never sees your key.

By hand instead:

```
python3 bootstrap.py all          # check, download MarketStore, key file, MCP registration; asks first
python3 bootstrap.py run demo     # a short walk in view mode, about six minutes
```

The two example projects are MarketStore and Apache Ignite. `python3 bootstrap.py demo` keeps MarketStore as the
default; `python3 bootstrap.py demo ignite` gets Ignite, and `python3 bootstrap.py demo all` gets both. Source
downloads are pinned and verified before use.

## How you use it

Three windows work together:

| Window | What you do there |
|---|---|
| **The page in your browser** (the player) | Listen. It shows what is being said: the caption, the code, the schema with the named parts framed. Play and Pause (Space), next and previous, the contents, the speed. **Q** asks a question at the current place; **D** stops the walk to discuss it. |
| **Your coding agent** (the one that set codewalk up: Codex, Claude Code or Copilot) | The console. Ask it in plain words: "start the design walk", "stop", "go to the chapter on modules", "slower", "where am I?". When you press D in the page, it discusses the point with you, amends the walk into a new version, and the page continues where you were. While it waits, the page shows "The session is listening for questions and Stop & discuss notes." or, with an answer helper, adds "the session is listening too." |
| **IntelliJ IDEA** (optional) | Opens each file at the line being spoken about. |

The agent needs nothing special for this: [README-r.md](README-r.md) tells it which commands to run.

## Export

A bundle holds one walk version, its diagrams, and a project reference pinned by commit and source-file checksums;
local-only projects need a matching `--project-root` when played. It contains no audio and no source code by default.
`--with-code` adds whole referenced files only for recognised Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause or ISC
licences, with the licence, NOTICE if present, and attribution; other licences produce a reference bundle
(`--strict` refuses instead). Existing output files are never overwritten.

```
python3 codewalk.py export --script walks/ignite-thin-client/ignite-thin-client.walk.json --project-root demo/ignite-2.17.0 --out ignite.codewalk.zip
python3 bootstrap.py run --bundle ignite.codewalk.zip --background --no-open
```

The player verifies bundled code, a supplied local project, or just the referenced files downloaded at the pinned
GitHub commit; an existing pinned example download is a fallback. A checksum mismatch stops playback.
Hashes are byte-exact: for a CRLF/LF mismatch, use a checkout with `core.autocrlf=false` or a fresh clone configured that way.
`python3 codewalk.py serve --bundle ignite.codewalk.zip --no-ide` also works; IDEA follow needs `--project-root`.

## What leaves your machine

With your explicit Azure consent, narration text goes to Azure Speech and spoken-question audio goes to Azure speech-to-text. With your explicit Claude consent, the answer helper sends your question, current phrase, nearby code, paths, diagram and earlier questions to Claude (Anthropic). The helper is off without yes; `--answerer claude` opts in for that run only. Decisions are kept in `~/.config/codewalk/consent.json`; change them with `python3 bootstrap.py consent --azure yes|no --claude yes|no`.

Without Azure consent, narration and spoken questions are off; captions and text questions still work. Questions, answers and notes are kept locally under `runs/`; delete that folder to remove the transcripts. Cached audio and its text metadata live separately in `cache/tts/` (or `CODEWALK_CACHE_DIR`); remove that cache too to erase cached spoken answers.

## Your narration

The voice is made with your own Azure Speech key, once per phrase, and kept in `cache/tts/` (one mp3 per phrase,
named by the voice and the text; git ignores the folder, so `git pull` leaves it alone). It is reused every time:

- playing a walk again, restarting the player, or pulling a new version of this repository needs no new clips;
- after an amend, only the new or changed phrases are narrated; the others keep their clips;
- walks that share a sentence share its clip (the short demo reuses the full walk's clips);
- another voice makes its own clips.

To share the clips between copies of this repository, point them all at one folder with `CODEWALK_CACHE_DIR`, or copy
`cache/tts/`. `python3 bootstrap.py check` shows how many phrases of each walk already have a clip.

Clips made with a free key are for your own listening; publishing audio needs a paid tier (Microsoft grants output use rights only to paid-tier customers), and a published synthetic voice must be disclosed as such.

## Walks in this repository

| `bootstrap.py run ...` | Walk | Length |
|---|---|---|
| `demo` | MarketStore in five minutes, view mode | about 6 min |
| `marketstore` | Alpaca MarketStore v4.1.23 (commit 0075865) with its schemas | about 37 min |
| `ignite` | Apache Ignite 2.17.0: the thin client, from the API to the cache and back | about 22 min |
| `guide` | An interactive guide to the player | about 3 min, plus your tries |
| `design` | The design of codewalk, through its own code | about 6 min |

## Requirements

- Python 3.10 or newer (standard library only) and a browser.
- An Azure Speech key to hear the walks; the free tier is enough for listening (`python3 bootstrap.py azure`
  shows how to get one). The narration is synthetic speech generated with your key.
- Optional: ffmpeg (spoken questions), the `claude` command-line tool (answers to questions),
  IntelliJ IDEA on Windows with WSL (the IDE follows the code).

On Windows, safe IDEA follow polls the foreground process name and ID only while follow is on.
Setup keeps the key file and IDEA config under `~/.config/codewalk/` by default, and the player listens on `127.0.0.1`.

## Licence

Source-available, not open source: [PolyForm Strict License 1.0.0](LICENSE), with an
[additional permission](ADDITIONAL-PERMISSION.md). You may use it for any noncommercial purpose, and change your own
copy for your own noncommercial use: change the player and the page, adapt the prompts, amend the walks, write walks
of your own projects. You may not
distribute it, publish changed versions, or use it commercially without a separate licence from the author.

Pull requests are not accepted. Issues and feedback are welcome.

The example walks describe MarketStore (Apache-2.0, by Alpaca) and Apache Ignite (Apache-2.0, by the Apache Software
Foundation). Their source code is not part of this repository; codewalk is not affiliated with or endorsed by
either project. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

arahet™ is a trademark of William Molodchenko, used but not registered. The licence does not grant any right to use
the name arahet.

Copyright 2026 William Molodchenko (molodchw@gmail.com)
