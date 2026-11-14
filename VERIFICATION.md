# Verification

- 2026-11-14: the `requires_hermes` floor in `plugin.yaml` is now `>=0.22.3`, matching the catalog entry (catalog rule 14). No code changed; validation was re-run on the commit.

- Mixed-case protected-directory fixtures passed on Linux and native Windows; no real credentials were used. This is not a full platform or publication audit.

- Saved public opinion text can be read in bounded offset-preserving pages; synthetic tests cover Unicode, reconstruction and invalid bounds. Reading the extract does not establish that the source or extraction is complete.
- Native Windows Python 3.14 on a separate machine passed saved-source paging and one robots-checked fetch of each selected public Katz OpenJurist page. The expected disposition phrases appeared; Justia remained a reference. Source completeness, legal review, Windows ACL behavior and full platform support remain unverified.

- Twenty-nine synthetic tests cover domain filtering, separate text provenance, malformed search responses, party-name query construction, reporter-abbreviation spacing, forwarded session context, extraction URL changes, local opinion files, symlink and atomic-replacement rejection, private review receipts and corruption detection, saved-source change checks, changed-source quote validation, failure reporting, bounded match truncation, late and emphasized disposition passages, reporter-citation dispositions, ambiguous reversal references, partial direct history, invented quotations and dissent versus overruling.
- Hermes catalog validation and Plugin Doctor passed on the development build.
- A Hermes-runtime fixture saved a private review, reopened it by ID and listed it without including its analysis in the listing.
- The examiner processed the text of an existing local Justia opinion capture from LegalHelper and found citation and disposition cues. This exercised real extracted source formatting; no legal conclusion or full-reading claim was made, and the source is not bundled.
- A separate locally preserved appellate opinion exposed a missed emphasized disposition near the end. The updated pattern now surfaces that passage as an unverified lead; the opinion and any user matter are not bundled.
- A live Hermes web search for the parties in a historical appeal returned Justia links for both the Fifth Circuit and Supreme Court opinions, including after the party-name query was corrected to preserve apostrophes. Search results alone are not verified treatment.
- On the separate public Katz test case, an initial general citation search found the Ninth Circuit opinion but omitted the Supreme Court opinion. A Supreme Court-scoped citation query subsequently found the higher-court lead. Search results varied on a later combined rehearsal, which did not reliably return both links; discovery remains incomplete and provider-dependent.
- A real-source Katz integration used locally saved text from OpenJurist for the lower opinion and the official U.S. Reports for the higher opinion, with Justia links recorded separately as references. It checked exact passages from both, an unrelated-reversal trap, and detection of a changed source. The finding remains proposed and passage-level; neither source provenance nor legal interpretation is automatically authenticated. No Justia opinion text was fetched live or bundled.
- Live Justia opinion extraction remains unverified: the configured Hermes backend reports that it is search-only. Direct requests to one Supreme Court opinion and one separate law.justia.com appellate opinion each returned HTTP 403. The plugin exposes errors and does not bypass access restrictions. An alternative permitted public case-page route is available as described below.
- The plugin has no completeness benchmark, automatic independent legal review, paginated pincite validator, desktop UI, demonstration, release audit or proof of compatibility with Justia's terms for the contest. It is not release-ready.

- A bounded live Katz test fetched the lower and higher OpenJurist public case pages after checking robots.txt for each; it found the relevant passages, rejected a different-case reversal as proof, saved a proposed receipt, and detected swapped source IDs. Justia links were references, not text sources. Identity, OCR, completeness, independent legal review and present legal status remain unverified.
- Synthetic public-source tests cover conservative robots enforcement (including disallow overriding a broad allow), malformed policies, excessive crawl delay, no retry on HTTP 429, public-address enforcement, URL validation, private source storage and tamper detection. Hermes runtime discovery and registered skill, mock host workflow and catalog validation passed with thirteen tools.
- 2026-11-07: BUG FIXED. The earlier bulk rename left the tool-dispatch prefix stale (`removeprefix('justia_')`), so every tool that goes through the core dispatch (for example caselaw_examine) failed with AttributeError when called through Hermes, although the unit tests passed. Found by running the real tool in the demo maker. New regression test calls caselaw_examine through invoke and checks that no registered tool name fails to resolve; it fails on the old code. 30 tests pass.

##2026-11-10 supplied-source portability

Added provider-independent text/file examination and labeled-source review/save.
No fake Justia reference is needed.33offline/mocked regressions pass, including
three new source/URL/evidence/authority/storage-continuity tests. Original Justia
contracts and existing review provenance checks remain intact. No live legal
research, model API, repository account or legal correctness certification was
performed. Current schemas, admission and source preflight are recorded separately.

- 2026-11-10 (0.3.0): evidence may be cited by unique anchor or by location; the quote is filled from the file and the exact-match guard is unchanged. Offline test added (anchor, location, absent, ambiguous and out-of-range cases); 34 tests pass. No live provider use.
- 2026-11-10 (0.3.0, after first real-Hermes attempt): the assistant found anchor citing by itself, then failed on (a) `source_label` (used by the examine tool) versus `label` in review sources and (b) unguessable relation value. Now `source_label` is accepted, the tool schema lists the allowed relation/treatment/extent/opinion_role values and the source/evidence fields, and an anchor matches across line breaks (the file's own exact text is stored). 35 tests pass.
- 2026-11-10 (0.3.0, after second real-Hermes attempt): a missing anchor now returns the closest exact passage from the file; date fields say to omit when unknown (the assistant had guessed 1966-01-01). 36 tests pass.

## 0.4.4 - maintainer review (2026-11-12)

Maintainer review. Opinion files are read only from folders the owner lists in the opinion_folders setting (plus the working folder); system folders, Hermes home, auth.json, .claude, .gemini, keyrings and browser profiles are refused. Re-tested: 45 offline tests, all passing; plugin preflight reports no findings.

Live test through Hermes 0.23.0 (2026-11-12, own profile): installs through the Hermes scanner, reads a real opinion file, refuses .env, .claude and kernel files. Found and fixed: the install scanner flagged a kernel path in a comment and the tests.

## 0.4.0 (2026-11-11)

Tests: date must appear in its own source (accepted when stated, refused when not, fine when omitted) and the rendering shows quotes, places and limits, escapes HTML and writes a private file. 38 tests pass with the Hermes interpreter path (a standalone interpreter lacks the plugins module for older tests).

## 0.4.1 (2026-11-11)

Text-only change after a live run used the Justia-only review tool on local files and stopped.

## 0.4.2 (2026-11-11)

Rendering tests unchanged in substance; one call now returns both file paths.

## 0.4.3 (2026-11-11)

Title test added to the rendering test.
