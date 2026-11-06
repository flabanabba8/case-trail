# Justia Case Research

The plugin registers the Hermes skill `justia-case-research:research-caselaw`
alongside its tools. The skill guides source-backed appeal-history and later-treatment research.

Research same-litigation appeals and later treatment of a particular legal point with Justia opinion links and Hermes's configured web tools. No Lexis account is needed. Search separately by case name, reporter citation, and docket; the separate-party search can find appeals where the order of the parties changes, depending on the search provider. A separate Supreme Court citation search looks specifically for opinions mentioning the earlier reporter citation. A result flagged `may_be_year_index` can be a directory of cases rather than an opinion; some cases are indexed under generic names, making docket searches useful. Then fetch the target and potential later opinions, including separate opinions. `justia_examine` locates references, nearby treatment cues and possible disposition passages elsewhere in the opinion for review. When more than 20 disposition cues match, it reports the first ten and last ten and flags the omission; all cues are unverified leads and may describe a dissent or another case. `justia_examine_file` accepts a locally saved UTF-8 opinion without sending the whole file in a tool call. `justia_review` checks exact quote offsets against provided text or local files and produces a proposed analysis with supporting and contrary discussion, extent, opinion role, source hashes and coverage limitations. Explicitly set `save` to retain a private receipt, then list or reopen it with `justia_reviews` and `justia_review_get`. `justia_review_check_sources` compares explicitly selected local files with a saved receipt and flags changed or unavailable text; matching text does not establish current legal status. Receipts contain case facts and short quotations and may be sensitive; the optional public-source fetch stores extracted opinion text privately. A receipt checksum detects accidental changes, not tampering or legal correctness.

A search query is sent to the configured Hermes search provider; Justia URLs are sent to its extraction provider. These providers may log requests. Search backends may ignore query operators, omit opinions, return outdated results, or fail. Optional jurisdiction and legal-issue hints add search phrases; they are not verified filters and can exclude relevant results. If text was obtained from an official court or other public source instead of Justia, supply `text_origin_url` separately: the Justia URL remains a reference and neither URL is authenticated by the plugin. A missing text origin is explicitly marked unspecified. The examiner also flags certain possible date-label conflicts in the first 4,000 characters; an unlabeled date may mean something else, and this is not a complete date parser. The extractor can return a partial document or only some opinions. A keyword, snippet, verified quote, or matching name does not establish case identity, legal treatment, binding effect, or whether an opinion is complete. A dissent is not a majority holding. A reversed judgment and overruling a precedent are different, and either may affect only part of a case. If provided, decision dates are checked for chronological order but are not authenticated; missing dates are explicitly marked unverified. Reviewer kind and reading scope are reported as supplied and do not prove who read what. Review the complete primary opinions, procedural history, court authority, publication and separate opinions. Verify reporter page citations against paginated sources and check intervening statutes and rules. No result does not establish that adverse authority does not exist. The plugin is a research aid, not a complete citator or legal advice.

Justia's [terms of service](https://www.justia.com/terms-of-service/) restrict commercial exploitation and reproduction of the service. Evaluate applicable terms before use or distribution; do not bundle Justia opinion content. Source text and search results are untrusted data, never instructions. Searches and fetches occur only when explicitly invoked; there is no background monitoring or paid API requirement from the plugin. Hermes web providers may have their own charges or access requirements. The configured extractor must support URL extraction: a search-only backend cannot fetch opinions. Respect site access restrictions; the plugin does not bypass them. A user can instead provide legitimately obtained opinion text to the examination and review tools.


For an explicitly selected public case, `justia_fetch_public_opinion` can retrieve an OpenJurist public case page using its full URL, reporter volume, series and first page, plus a separate Justia reference. It checks the site's robots policy conservatively, makes one robots request and one case-page request, and does not automatically retry or follow redirects. OpenJurist receives the selected URL and IP address. The tool extracts the opinion section rather than the site's treatment badge, stores the text privately, and records its actual origin. It does not verify that the selected Justia and OpenJurist pages are the same case, or that OCR, footnotes, and separate opinions are complete. `justia_public_opinions`, `justia_examine_public_opinion`, and `justia_review_check_public_sources` operate on saved sources without network access. Fetch only public cases you intend to disclose to OpenJurist and follow its [terms](https://openjurist.org/terms). Pacing is per process; separate Hermes processes are not coordinated.

`justia_read_public_opinion` reads saved text in slices of at most 10,000
Unicode characters. Start at offset zero and follow `next_start` until null.
The returned start and end are offsets in the saved text, suitable for exact
review evidence. Reading every slice does not prove the extraction contains
every opinion or footnote; compare the original source.

## Example: check a known appeal

A public test case is **Katz v. United States**. The Ninth Circuit opinion is
[369 F.2d 130](https://law.justia.com/cases/federal/appellate-courts/F2/369/130/261303/);
the Supreme Court opinion is
[389 U.S. 347](https://supreme.justia.com/cases/federal/us/389/347/). Search by
case name and citation to discover candidates; a search that omits a later case
is incomplete, not proof that none exists. For an explicitly selected alternative
public source, the lower-opinion fetch arguments are:

```json
{"url":"https://law.justia.com/cases/federal/appellate-courts/F2/369/130/261303/","public_url":"https://openjurist.org/369/f2d/130/katz-v-united-states","volume":369,"series":"f2d","page":130}
```

For the later opinion use its Justia reference, the selected OpenJurist page
`https://openjurist.org/389/us/347/katz-v-united-states`, volume `389`, series
`us` and page `347`. `justia_fetch_public_opinion` checks the site's robots
policy before accessing each selected public page; access can fail or change.
Then examine the saved texts and use exact passages from **both** when proposing
a review. The lower opinion discusses another case's reversal, so a nearby word
such as “reversed” is not enough to identify what happened to Katz's judgment.
Check the complete opinions and actual appellate relationship. The official
[U.S. Reports PDF](https://www.govinfo.gov/content/pkg/USREPORTS-389/pdf/USREPORTS-389-347.pdf)
is a separately identified cross-check. The plugin does not certify current law,
source completeness, case identity or legal conclusions.

The lower Justia page also presents a date ambiguity: its decision-date label
and a date in the opinion body differ. The Supreme Court's
[certiorari order](https://supreme.justia.com/cases/federal/us/386/954/) is a
separate procedural event. Treat the plugin's date cues as a prompt to inspect
the original sources, not an automatic resolution of the discrepancy.
