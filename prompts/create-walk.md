# Creation prompt: write a codewalk walk

Give this prompt to your coding agent (Claude Code, Codex) together with two paths: the project to explain and
this repository. Replace the parts in angle brackets; keep or change the plan. The walk follows the prompt, so
the same player can give an onboarding tour, an architecture review or the story of one change.

---

Write a codewalk walk for the project at `<project path>`, using the codewalk repository at `<codewalk path>`.
Follow the accuracy rules in `prompts/accuracy-addendum.md` (attach that text to this request).

**Purpose and audience.** `<who will listen, and what should they understand or be able to do afterwards>`

**Plan** (one chapter per part):
1. Overview: what it does from the business point of view.
2. Preparations: versions, build, top-level structure; how to run the build; the configurations.
3. Main design ideas: requirements and assumptions, supported with code and schemas.
4. Modules: each module and its main features, with schemas.
5. Top-level workflows: a schema for each, the call hierarchy, where to debug, the logs.
6. Other notes and open questions.

**Depth and length.** `<for example: about 20 minutes; every module, but contrib only briefly>`

**How to write it**
- Format: codewalk-script-v1 JSON in a new folder `walks/<name>/`; a complete example is
  `walks/marketstore/marketstore.walk.json`. Put this prompt into `operator.task` and `operator.guidance`.
- Set `project.root` to the project path, or to a path relative to the walk file.
- Phrases: one or two spoken sentences each, plain spoken English; no markdown, lists or code in the text.
- Every statement about the code gets a code pointer: `file` (relative to the project root), `start`, `end`,
  and `anchor`, a few words copied exactly from inside that range.
- Schemas: PlantUML sources in `walks/<name>/assets/`, rendered to SVG in `assets/svg/`
  (`java -jar plantuml.jar -tsvg -o svg assets/*.puml`). Give every part an alias. In a phrase, list the aliases
  it talks about in `diagramComponents` and exact texts to highlight in `diagramFocus`.
- Place a schema's part-by-part narration just before the code that implements it.
- Builds, test runs, debug sessions and logs: write them as an `action` with status `planned` or
  `needs-approval`. Do not run them.
- Do not copy the project's source files into the walk folder.

**Check, then hand over**
- `python3 codewalk.py validate --script walks/<name>/<name>.walk.json --project-root <project path>`; fix every
  finding until it passes.
- Go through the cross-check of `prompts/accuracy-addendum.md` (rule 11) and say what you did not verify.
- Have the walk reviewed independently with `prompts/review-walk.md` and fix the findings.
- `python3 codewalk.py outline --script ...` gives a readable copy; show it to me before I listen.
- Then I play it: `python3 codewalk.py serve --script ... --project-root <project path>`. For changes while I
  listen, follow `prompts/discuss-and-amend.md`.
