---
name: research-caselaw
description: Research case history and treatment from available opinion sources, preserving passages, provenance and review limits.
---

Read the [bundled LLM wiki](../../llmwiki/index.md), especially the setup/task guide.
Start with the exact case, jurisdiction, proposition and the sources the user has.
Reuse known answers. Ask missing resource/privacy/budget questions only in ordinary
chat; subscription access is not proof of API entitlement. Do not read account
stores or silently install, download, upload or spend.

Choose sources before choosing a backend. If opinion text/files already exist,
use caselaw_examine_source or caselaw_examine_source_file with a descriptive label
and only a real optional URL. If the active host has an appropriate native search,
browser or document reader, use that supported interface and preserve provenance,
reading scope and source errors. Justia/OpenJurist helpers are optional adapters;
never invent their URLs to satisfy an interface.

Read complete relevant opinions and separate opinions before drawing conclusions.
Use identifiers and excerpts as leads, not a citator. Keep same-litigation appeal
history distinct from later treatment and record court authority and chronology.
caselaw_review_sources validates exact evidence from two labeled text/file sources
and can save a proposed private receipt; it does not authenticate dates, sources,
authorship or legal correctness. Recheck source hashes after changes.

Reason and write in the active harness. No new reasoning-model API or agent worker.
Images/scans need appropriate main-session native vision/OCR and explicit review;
unavailable access is a specific blocker, not a text-only or placeholder success.
Preserve uncertainty, private notes, original sources and existing pauses. Public
sharing requires separate authorization and exposure review.

When the user asks to see, open or explain a saved review, call `caselaw_review_render` with its review ID and show the
result readably: the title, the answer in a sentence, each quoted passage with the opinion it comes from and its place, why
and what points the other way, and the limits. Give the path of the HTML page it wrote (`html_page`; copy it to the user's folder if they
want it there). Do not paste raw JSON.

Dates: put a decision date in a review only if the source file itself states it (the plugin refuses a date that does not
appear in that file). Leave the field out otherwise; never fill it from memory.

Which review tool: opinion files the user already has (a folder of .txt files, with or without a sources note) go through
`caselaw_examine_source_file` and then `caselaw_review_sources` (give each source a label and its `source_path`; use
`save: true`). `caselaw_review` is only for text that came from Justia pages. Cite each quote by a short `anchor` phrase.
If one tool refuses, try the other that fits the sources instead of stopping; never end without saving the review when
the user asked for one and the files are readable.
