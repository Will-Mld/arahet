# Session prompt: stay with a running walk, discuss, amend, continue

Give this to the coding agent that wrote the walk (or any session) while the walk plays. The player must be
running; `CODEWALK_URL` points at it if it is not on the default port.

---

Stay with my running codewalk walk and keep it correct while I listen.

1. **Listen without polling.** Run `python3 codewalk.py ctl wait --after <last seq> --timeout 60` in the
   background (or the MCP tool `codewalk_wait`). It returns as soon as I ask a question or stop to discuss.
2. **Questions.** Answer briefly in spoken English with
   `python3 codewalk.py ctl answer --qid <id> --text "..." [--file F --line N --end M]`. The answer is spoken and
   the code range is shown.
3. **Stop and discuss.** When I press D, my note and my place (phrase, version, audio offset) come with the
   record. Talk it over with me here. The walk stays paused at my place.
4. **Amend.** Write the agreed change as a patch file and apply it:
   `python3 codewalk.py amend --script <current version> --patch <patch.json>`.
   It writes the next version beside the current one, validates it, never overwrites a file, and adds a line to
   `changelog.jsonl`. Put my words in `quote` and the reason in `reason`.
5. **Reload.** `python3 codewalk.py ctl reload --script <new version>`. My place is mapped onto the new version;
   changed phrases are played again; earlier corrections can be replayed first. Then tell me to press Continue.

Patch operations (in `ops`, applied in order):

```json
{"reason": "why", "quote": "the listener's words", "by": "who amended",
 "ops": [
  {"op": "replace_text", "phrase": "c3.p2", "text": "new spoken text"},
  {"op": "set_code", "phrase": "c3.p2", "code": {"file": "x.go", "start": 10, "end": 20, "anchor": "func X"}},
  {"op": "insert_after", "phrase": "c3.p2", "phrases": [{"id": "c3.p2a", "text": "..."}]},
  {"op": "insert_before", "phrase": "c3.p2", "phrases": [{"id": "c3.p1a", "text": "..."}]},
  {"op": "insert_item_after", "item": "c3.i1", "newItem": {"id": "c3.i1a", "title": "...", "phrases": []}},
  {"op": "insert_chapter_after", "chapter": "c3", "newChapter": {"id": "c3a", "title": "...", "items": []}},
  {"op": "delete", "phrase": "c3.p4"},
  {"op": "retitle", "target": "c3.i1", "title": "new title"}
 ]}
```

Keep unchanged phrases' ids; give new phrases new ids. Never edit a version file in place.
