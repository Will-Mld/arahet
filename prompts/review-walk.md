# Review guidance: checking a walk before anyone listens

A walk is ready when an independent review has found nothing that is false and of high or medium impact, and its
findings are fixed and re-checked. This guidance comes from the first such review, of the MarketStore walk:
57 findings, all confirmed against the code, and from a second review of the corrected walk: 12 findings, one of them
introduced by a fix.

## How to run the review

- **Independent.** Use a reviewer in a fresh context: another agent session, or a person. Give it:
  - the walk (`*.walk.json` and its `assets/`);
  - the project's code at the walked version;
  - the user's original request.

  Do not give it the author's conclusions or the claims ledger in the first pass. A reviewer who is handed the
  author's reading tends to confirm it.
- **Two reviews in parallel.** A technical review (the walk as a script and as something the player plays) and a
  correctness review (every claim against the code).
- **Read-only.** The reviewer changes nothing. If its sandbox limits reading, copy the walk and the project into its
  working folder.
- **Coverage, not a sample.** Every phrase, every pointer, every diagram element. Say what was only sampled.

## Report format

- Verdict:
  - technical: ready / ready after fixes / not ready;
  - correctness: trustworthy / trustworthy after fixes / not trustworthy.
- A findings table: id | how wrong | impact | location (phrase id, diagram line) | the claim as written | what the
  code shows (file:line) | corrected wording.
- Counts per class, what was checked fully, what was sampled, what could not be checked (for example, no Python in
  the sandbox).

## A. Technical checkpoints

| # | Check |
|---|---|
| A1 | `codewalk.py validate` passes: schema, unique ids, files exist, ranges within the file, anchor inside its range. |
| A2 | Each code range shows what its phrase says: the right function, the right branch, not just the function's first lines. Check the end line: the decisive write, call or check must be inside. |
| A3 | Each `diagram`, `diagramFocus` and `diagramComponents` name exists in that diagram's SVG and PlantUML source. |
| A4 | A schema is narrated just before the code that implements it. |
| A5 | Flow follows the request's plan: no gaps, no repetition, no leftover authoring questions or notes to self. |
| A6 | Phrases can be spoken: about 40 words at most; no paths, symbols or code the voice will read badly; abbreviations explained. |
| A7 | Actions (build, tests, debugging, logs) are visible on the page, with their status, and the walk stops where the listener must act. They work as written: the command exists in this version, and a debug action uses a debug build. |
| A8 | Wording does not depend on layout ("on the left") or on the reader's screen. |
| A9 | Nothing personal or unfinished: no personal paths or user names, no placeholders such as `<author name>`. |
| A10 | The walk states its length. Estimate it at the voice's real rate, about 135 words a minute for the default voice, plus 0.7 s between phrases; once it is narrated, `bootstrap.py check` gives the length from the clips. 150 words a minute underestimates by about 10%. |

## B. Correctness checkpoints: the typical traps

Classify each phrase as correct, wrong, misleading, unsupported, or planned/non-factual. Look hardest at these places:

| # | Trap | How to check | Example from the reviews |
|---|---|---|---|
| B1 | Design document presented as the implementation | Find the code. Check the document's date against the version walked. | read-committed visibility; owner detected by PID; WAL state table |
| B2 | README "limitations" or "currently" statements | Find the code that implements or removes the limitation. | "a replica connects only at start" (it retries) |
| B3 | Stale code comments | Trust variable names and behaviour over comments. | a comment says "writing our PID", but the code writes an instance ID |
| B4 | Guarantees: always, only, refuses, read-only, durable, atomic | List every entry point and caller; check each one. | HTTP writes guarded, gRPC Write not |
| B5 | Main branch stated as the rule | Read the whole function: special cases, early returns, error paths. | the 1D index formula; `RequestFlush` returning early |
| B6 | State machines and diagrams | Map each state and transition to the call that writes it. | shutdown writes no WAL status |
| B7 | Reused content | Re-check phrases and diagrams that came from another walk or an earlier version. | one wrong diagram in three walks |
| B8 | Guesses written as fact | Words like usual, always, exactly, same, in this order, built with. | "the usual cause", "the toolchain it was built with" |
| B9 | Pointer near the claim, not at it | The range must contain the behaviour named, up to its last line. | `readForward` shown for "reading backward"; a range ending one line before the slot write it describes |
| B10 | Names and comments read as behaviour | Function or flag names are not specifications. | Queryable "gates queries" |
| B11 | Facts in diagram labels | Treat every label that states a field, format, size or order as a claim; find its code. | a box listing "Epoch seconds + Nanoseconds" for stored records that hold neither |
| B12 | Text written by a fix | Check corrected sentences and labels against the code, not only that the old finding is gone. | that same label, introduced by the previous round of fixes |

## C. Omission checkpoints

Is each of these explained, or explicitly marked as out of scope?

- durability and failure guarantees;
- recovery after a crash;
- concurrency and ownership;
- replication and consistency;
- flow control: bounded queues, blocking calls, what stalls when a consumer is slow;
- security and trust boundaries;
- variants of the data format;
- defaults and special modes (local, bypass, debug);
- known limits and TODOs;
- how the reader can run or reproduce what is shown.

## D. Severity

| How wrong | Meaning |
|---|---|
| Plainly false | Someone who believes it is wrong about this version. |
| Partly true | True in the main case, wrong in an exception, or overstated. |
| Unsupported | Might be true; nothing shows it. |
| Poorly shown | The sentence is right; the code shown is the wrong part. |
| Missing | Nothing wrong; something important is left out. |

| Impact | Meaning |
|---|---|
| High | Wrong expectations about guarantees people rely on: durability, consistency, security, ownership. |
| Medium | Recovery, edge cases and behaviour that surprises an operator or a developer making a change. |
| Low | Detail, naming, build trivia, wording, presentation. |

A walk ships only with no finding that is plainly false with high or medium impact, and with every high-impact
omission either explained or marked as out of scope.

## E. After the fixes

- Re-review the changed phrases and diagrams. The first verdict was about the old text. A fix can introduce a new
  error: check every corrected sentence and label against the code (B12).
- Rebuild and re-validate everything that depends on the fixed walk: demo cuts, tours, and walks whose pointers
  point into changed files.
- Keep the findings, the fixes and the re-review next to each other, so the walk's history shows what was checked.
