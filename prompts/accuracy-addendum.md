# Accuracy addendum: attach to every request to write a walk

Add this text to the request whenever an agent writes a new walk (`create-walk.md`) or a large part of one. It comes
from an independent review of a walk written by a strong model: 24 of 167 phrases were wrong or misleading and ten
important topics were missing. Few errors came from hard code. Most came from stopping at the first source that
looked authoritative - a design note, a README, a confirming code fragment, a stale comment. Rules 13-17 come from a
second review, of the corrected walk: 12 findings, one of them a false diagram label introduced by a fix.

---

**Accuracy rules for this walk**

1. **Claims ledger first, phrases second.** Before writing phrases, write `walks/<name>/<name>.claims.md`: one row
   per statement you intend to make, with
   - the claim;
   - its source: `code file:lines`, `design document`, `README or docs`, or `inference`;
   - the exceptions and limits you found (special cases, error paths, "only", "except", "not yet", "TODO",
     "beyond the scope");
   - how you checked it.

   Write the phrases from the ledger. When you shorten for the listener, never drop a limit that changes whether the
   sentence is true.
2. **The code of this version is the authority.** Design notes, READMEs, code comments, tickets and commit messages
   are claims to verify, not facts. Confirm every statement about behaviour in the code. If only a document says it,
   say so ("the design note says..."), and where the code differs, say what the code does.
3. **Read the whole unit.** Read a function including its early returns, special cases and error paths. Read a
   document section including the paragraphs after the claim, because caveats follow claims.
4. **Guarantees need every path.** For "always", "never", "only", "all writes", "refuses", "read-only", "durable",
   "atomic": find every entry point and caller (search the call sites) and confirm each one. Two sources that agree
   are not proof.
5. **Report inconsistencies.** A path that behaves differently from the others (an unguarded handler, a renamed
   field, a stale comment, a TODO in the critical path) is a finding to narrate, not noise to smooth over.
6. **Diagrams say where they come from.** Put the source (code, or the design document and its date) in the
   diagram's title or a note. Every state, transition and arrow must map to code: for a state machine, find the call
   that writes each state. A diagram drawn from a document is labelled as design, or corrected to the code.
7. **Re-check whatever you reuse.** When a phrase or a diagram moves into another walk (a tour, a merge, a demo cut),
   check it again against the code before it ships.
8. **No guesses as facts.** "Usually", "always", "exactly", "the same", "in this order", "built with" need evidence.
   Otherwise soften the sentence or drop it.
9. **One pointer per claim, at the claim.** The range shows the lines that do what the phrase says, not the start of
   the function. Split a phrase that makes two claims.
10. **Cover the operational truth.** For a system, cover or explicitly list as not covered: durability and failure
    guarantees, recovery, concurrency and ownership, replication and consistency, flow control (bounded queues,
    blocking calls, what stalls when a consumer is slow), security and trust boundaries, variants of the data format,
    defaults and special modes (local, bypass, debug), known limits and TODOs.
11. **Cross-check before handing over.** Go through the ledger and check that:
    - every claim sourced from a document or an inference is checked in the code;
    - every guarantee has its paths listed;
    - every diagram element has its code, labels included (rule 13);
    - every code range contains its decisive line (rule 14);
    - every sentence or label you corrected was checked again (rule 17).

    Then ask for an independent review (`prompts/review-walk.md`).
12. **Say what you did not verify.** End the hand-over with what you could not check and why.
13. **A diagram label that states a fact is a claim.** A field, a format, a size or an order written in a box goes into
    the ledger and is checked in the code like a phrase.
14. **The range must contain the decisive line.** Check the end line: the write, the call or the check the phrase names
    must be inside the range, not one line after it.
15. **Planned actions must work as written.** A debug action needs a debug build: check the build flags and which
    binary the action uses. A build or test command must exist in this version (read the Makefile or build file).
16. **Speak for the ear.** Never refer to a position on the screen ("on the right"); name the part. Say what an
    initialism stands for the first time it is spoken.
17. **A fix is new content.** When you correct a phrase, a label or a pointer, after a review or on your own, check the
    new text against the code again. A fix can be wrong too.
