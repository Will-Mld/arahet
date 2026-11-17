# README-r: set up codewalk with the user (a manual for the coding agent)

You are a coding agent (Codex, Claude Code, GitHub Copilot or similar). The user opened you in this folder and asked
you to follow this file. Your job: take the user from a fresh copy of this repository to a walk playing in their
browser, in one conversation, and then stay as their console for the walk: start and stop it, move around in it,
and discuss and amend it with them (steps 8 and 9).

How to work:
- Do the steps below in order, one step at a time.
- After each step, tell the user in one or two short sentences what happened, then go on.
- Ask the user only where this file says ASK, and wait for the answer.
- Where it says CONFIRM, show the result and ask the user to confirm before you go on.
- Keep your messages short and plain. Do not explain the code of codewalk unless the user asks.

## Rules (always)

1. Never ask for the Azure key. Never open, read, print, copy or search the key file, and never put a key on a
   command line. Only `bootstrap.py` and `codewalk.py` read the key file.
2. Do not install software, change system settings, create cloud resources, or commit or push anything; the user-level
   MCP registration in step 5 is allowed only after the user agrees there.
3. Change files only inside this folder, plus the files `bootstrap.py` writes itself (the key file and its
   config file).
4. If a command fails, show the user its last lines, say which step it was, and ASK what to do. Do not try
   another way on your own.
5. If your environment blocks a command, for example no network or no long-running processes, give the user the
   exact command to run in their own terminal, in this folder. Wait until they say it is done, then go on.
6. Use the same Python command, written PY below, in every step.

## Step 1 - Python

Try these commands in this order and use the first that prints Python 3.10 or newer:
`python3 --version`, then `python --version`, then `py -3 --version`.
On Windows, the message "Python was not found" comes from a Store shortcut, so try the next command.

If none works:
1. If your commands run in a sandbox (Codex does), the sandbox may hide the user's programs. ASK: "May I run the
   Python check outside the sandbox?" If yes, run the same three commands again with that approval. The later PY
   commands then need the same approval; say so once.
2. On Windows, also try the usual install folder, newest version first, for example
   `& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" --version` (the folders are `Python3NN`).
3. ASK the user where Python is installed, and try that path.

The command that worked is PY from now on, for example `py -3`, or the full path in quotes with `&` in front in
PowerShell. If nothing works, tell the user that codewalk needs Python 3.10 or newer, and stop.

## Step 2 - What is ready

Upgrading: existing keys or an installed Claude do not grant consent; review `PY bootstrap.py consent` and answer the questions in steps 4 and 5 if not decided.

Run `PY bootstrap.py check --json --quick`. It prints JSON. Report to the user in a short list:
- the Python version;
- both example projects from `projects`: `marketstore` and `ignite`, with `ready`, `path`, `version`, `commit`,
  and `obtained` (`demo` still describes MarketStore for compatibility);
- the Azure key file: `key.state`, which is `ready`, `template` or `missing`;
- the optional tools: `tools`;
- the five walks from `walks`, with `title`, `project`, `minutes`, and `narrated` of `phrases` (phrases that already have a
  clip; clips are kept and reused, so a walk narrated once is not narrated again).

CONFIRM.

## Step 3 - The example projects

Skip this step if both `projects.marketstore.ready` and `projects.ignite.ready` are true. Otherwise offer the
projects that are missing.

ASK: "Which example project(s) may I download: MarketStore v4.1.23 (about 1 MB), Apache Ignite 2.17.0 (about
29 MB with Git or 39 MB as an archive), or both? Both use the Apache-2.0 license and are pinned to the commits
their walks describe. MarketStore is fetched from the unofficial GitHub copies FluxAstromeshLabs/marketstore,
hickey/marketstore and nightsuns/marketstore, or the Go module mirror; its tree is accepted only if it matches the
pinned checksum from Go's checksum database. Ignite is verified against its pinned source-tree checksum. The
source files are made read-only."

The Ignite sizes were measured during integration; download time depends on the connection. Git checks out the
exact commit. If it is unavailable or its fetch fails, MarketStore uses the Go module mirror and Ignite uses
GitHub's archive.

Wait for the user's choice. Run one command for each project chosen and report each result:

- MarketStore: `PY bootstrap.py demo marketstore` (plain `demo` still means MarketStore). Success is
  `Verified against the Go checksum database`, followed by `477 files in ...`.
- Ignite: `PY bootstrap.py demo ignite`. Success is `Verified against the pinned tree checksum`, followed by
  `14336 files in ...`. The pinned commit is `d53d4540b64bb4a25f1a5a1003c4338727628c9f`.

An already downloaded project instead says `The demo project is already there and verified`. Any line starting
with `Refused` or `The download failed` is a failure (rule 4). A line saying no Git source gave the commit and the
mirror/archive is being used is not a failure; wait for its verification result. Re-run step 2 after the downloads.

## Step 4 - The voice

If `PY bootstrap.py consent` reports no Azure decision, ASK: "Narration text and spoken-question audio are sent to Microsoft Azure Speech; allow this?" Record the answer with `PY bootstrap.py consent --azure yes` or `--azure no`. Ask only when undecided. If no, skip voice setup and narration: captions and text questions still work.

Skip to the test below if `key.state` is `ready`.

ASK: "To hear the walk you need an Azure Speech key. Do you already have a key file? If yes, tell me its path. If
not, I will create one for you to fill in."

- **The user gives a path.** Do not open it. Set `CODEWALK_KEY_FILE` to that path for every command from now on:
  - in PowerShell: `$env:CODEWALK_KEY_FILE = "<path>"`;
  - in bash or zsh: `export CODEWALK_KEY_FILE="<path>"`;
  - if each of your commands starts a new shell, put the assignment in front of every command (for example
    `$env:CODEWALK_KEY_FILE = "<path>"; py -3 bootstrap.py ...`).
- **No key file yet.** Run `PY bootstrap.py azure`. It creates the key file and prints the steps for a free key.
  Tell the user the key file's path and those steps, then wait until they say the file is filled in.

Test: run `PY bootstrap.py azure --test`. Success is the line `The test worked: ... s of speech in <file>`. Tell the
user they can open that file to hear the voice. CONFIRM.

Tell the user in one sentence: "Clips made with a free key are for your own listening; publishing audio needs a paid tier (Microsoft grants output use rights only to paid-tier customers), and a published synthetic voice must be disclosed as such."

## Step 5 - Optional extras

If `PY bootstrap.py consent` reports no Claude decision, ASK: "Send your question, current phrase, nearby code, paths, diagram and earlier questions to Claude (Anthropic) for an answer?" Record the answer with `PY bootstrap.py consent --claude yes` or `--claude no`. Ask only when undecided; the helper stays off without yes.

ASK each of these, and do nothing for the ones the user declines:

1. "Should IntelliJ IDEA follow the code while you listen?" If yes, run `PY bootstrap.py idea`. If it lists
   launchers, ASK which one, then run `PY bootstrap.py idea --save "<that path>"`. Remember to add `--ide` in
   step 7 for walks other than `demo`: the demo is view mode and ignores `--ide`.
2. Only if `tools.claude` or `tools.codex` is true: "Should I register codewalk's MCP server, so your coding agent
   can drive the player?" If yes, run `PY bootstrap.py hook --dry-run`, show the command it prints, ASK again,
   then run `PY bootstrap.py hook --claude --yes` and/or `--codex --yes`.

## Step 6 - Choose the walk and its voice

If Azure consent is not yes, choose the walk below but skip narration and go to step 7 for captions.

ASK which walk to play. Offer the five from step 2 with their minutes: `demo`, `marketstore`, `ignite`, `guide`
and `design`. Suggest `demo` for a first look; `ignite` follows the Apache Ignite thin client from API to cache
and back. If the chosen walk's `project` is missing, return to step 3 for that project first.

If `walks[].narrated` equals `walks[].phrases`, every phrase already has its clip: tell the user and skip to step 7.

Otherwise ASK: "Shall I narrate the rest of the walk now? N phrases still need a clip; with a free key that takes
about M minutes. Otherwise each phrase is narrated the first time it plays." N is `phrases` minus `narrated`; M is
N divided by 18, rounded up (codewalk stays at 18 requests a minute; the current 239-phrase MarketStore walk would
take about 14 minutes by this estimate if none of its phrases were cached).

If yes, run `PY codewalk.py tts --script <walks[].path of that walk>` (phrases that have a clip are skipped at once). Give it that time, tell the user now and
then how far it is, and do not run it twice at once. Success is the last line with `"status": "PASS"`, `audio` (total
clips processed), `created` (new clips) and `cached` (reused clips). Report `created` as the number newly narrated.

## Step 7 - Start the player

Run `PY bootstrap.py run <walk> --background --no-open`, adding `--ide` if the user wanted IDEA and chose a walk other
than the view-mode `demo`. Success is the
line `PLAYER RUNNING: <address>`. Give the user that address and say:
"Open it in your browser and press Play. Space pauses, Q asks a question at the current place, D stops to discuss,
and at the end of a chapter press Continue."

Let the user press Play in the page. Do not start the walk yourself with `codewalk.py ctl` or the MCP server
before the user has clicked Play there once: browsers allow sound only after a click in the page. If the page
says "the browser blocked the sound", the user presses Play once more. If the walk is open in two tabs, the sound
plays only in the tab where Play was pressed last.

If your environment cannot keep a process running, follow rule 5 with the command
`PY bootstrap.py run <walk>`, without `--background`. To find out, run `PY codewalk.py ctl state --url ADDRESS` as a
separate command right after the start: if it cannot connect, your environment ended the player together with the
command that started it (Antigravity does this), so follow rule 5.

## Step 8 - Stay as the console

Tell the user: "I stay here as your console. Tell me what to do with the walk - start or stop it, another walk, a
chapter, faster or slower. When you press D in the page, I discuss it with you here and amend the walk."

ADDRESS is the address from step 7. Add `--url ADDRESS` to every `codewalk.py ctl` command. After each command,
tell the user in one line what happened; for "where am I" use the chapter, topic and phrase from `ctl state`.

On request, export with `PY codewalk.py export --script <current version> --out <file.codewalk.zip>`; add `--with-code` only if requested (fixed license allow-list), and no audio is included.

| The user says | Run |
|---|---|
| where am I / what is playing | `PY codewalk.py ctl state` |
| pause / play / continue | `PY codewalk.py ctl pause`, `ctl play`, `ctl continue` (at a chapter end) |
| next / back | `ctl next`, `ctl prev` (a phrase); `ctl next-chapter`, `ctl prev-chapter`, `ctl restart-chapter` |
| go to a chapter or topic | `PY codewalk.py outline --script <walks[].path>` to find the phrase id, then `ctl goto --phrase <id>` |
| faster / slower | `ctl speed --value <0.5 to 2.0>` |
| another walk, including `ignite` | `PY bootstrap.py stop`, then step 7 with that walk; give the new address |
| stop | `PY bootstrap.py stop` |
| what is set up | `PY bootstrap.py check` |

Send `ctl play` only after the user has pressed Play in the page once: browsers allow sound only after a click there.
If your environment asks for approval at every command, suggest that the user allows `PY codewalk.py ctl` and
`PY bootstrap.py` for this session.

## Step 9 - Discuss and amend (when the user presses D)

ASK once: "Shall I listen for your questions and Stop & discuss notes while you listen?" If yes:

1. Run `PY codewalk.py ctl state` and take `inboxSeq` as N. Then run `PY codewalk.py ctl wait --after N --timeout 90`
   again and again. It returns a record as soon as the user presses Q or D; after 90 s without one it prints
   `"timeout": true` and exits with code 2, which is not a failure (rule 4 does not apply). Between two
   waits, read any message the user typed and serve it (step 8) first. While you wait, the page shows "The session is
   listening for questions and Stop & discuss notes." or, with an answer helper, adds "the session is listening too."
2. A record of type `question`: if `ctl state` shows an enabled `answerHelper` (Claude installed and consent yes), the player answers it itself; do nothing. Otherwise answer briefly with `PY codewalk.py ctl answer --qid <id> --text "..."`.
3. A record of type `discussion`: the walk is paused at the user's place (`bookmark.phraseId`). Tell the user their
   note and the phrase, read the code it points at, and say what you would change. ASK before changing the walk.
4. If the user agrees, follow [prompts/discuss-and-amend.md](prompts/discuss-and-amend.md), steps 4 and 5: write a
   patch file in this folder, run `PY codewalk.py amend --script <current version> --patch <file>` (success:
   `"status": "PASS"` and the new version's file), then `PY codewalk.py ctl reload --script <new version>`. Tell the
   user to press Continue in the page.
5. Take the record's `seq` as the new N and go back to waiting. The current version is now the new file;
   `PY bootstrap.py run <walk>` starts the newest version from now on (`--original` starts version 1).

Stop listening when the user says so. Never change a version file in place; amend writes a new one.

## Step 10 - Finish

Tell the user:
- how to stop the player: `PY bootstrap.py stop`, or Ctrl+C in their own terminal;
- the other walks: `run guide` (how to use the player), `run design` (how codewalk works), `run marketstore`
  (the full MarketStore walk), `run ignite` (Apache Ignite's thin client);
- that `PY bootstrap.py check` shows the state at any time, and that you can be their console again in any session
  started in this folder.
