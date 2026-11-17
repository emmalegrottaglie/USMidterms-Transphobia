# Anti-trans rhetoric monitor: design

Repository: `emmalegrottaglie/USMidterms-Transphobia` (public, created 17 November 2026). Written 17 November 2026 from Emma's decisions in the session that started on 16 November. Items marked **(Claude's call)** are proposals Emma has not explicitly approved; everything else is hers.

## Intent

Measure anti-trans rhetoric on social media around political events, starting with the US midterm elections of 3 November 2026, and show it with strong graphics. The project grew out of the Bot Traffic Monitor (`C:\Russian bot tracker`, emmalegrottaglie/Russian-Bot-Monitor) but is a separate site and a separate codebase: it measures transphobic activity in general, not bots.

Why: Emma noticed a rise in anti-trans posting around the midterms, including newly created verified accounts, and wants to see whether it shows in the data. Republicans and allied PACs spent about $183M on trans-themed TV ads up to 25 October (AdImpact via AP), and Elon Musk funded a large share of them, so the question has public weight.

Audience: both the public and researchers. The public should be able to see what was collected and processed; researchers should be able to download the data and redo the work.

## Goals

1. A study page per event (the first: US midterms 2026) showing anti-trans term volume before, during and after the event against its normal level, with strong, honest graphics.
2. One standardised headline measure plus the detail for each term.
3. Every number traceable: each term's source, query, volume and hand-checked precision are published next to its chart.
4. Data downloads (CSV and JSON) for every series and every frozen study version, with a citation and a methods page.
5. Room to add sources later: Threads keyword search, Meta Ad Library, and named public figures.

## Non-goals

- Detecting bots, coordination or foreign operations. That is the Bot Traffic Monitor's question.
- Measuring "transphobia" as a whole. Keyword counts miss subtle and coded rhetoric (Lu and Jurgens 2022; Mendelsohn et al. 2023), so the site calls its measure "explicit anti-trans term volume" and says what it cannot see.
- Storing or showing posts, usernames or account IDs of ordinary users.

## Anti-goals (failure even if it works)

- Fabricated or zero-filled data: a failed fetch is a gap shown as `—`, never a zero.
- Overclaiming: titles describe what is plotted, never a conclusion; correlation is never called cause; every chart shows the normal range or a comparison next to the claim.
- Counting terms whose matches are mostly something else: only terms with hand-checked precision of 70% or more are tracked (Emma, 16 November 2026).
- Spending past Emma's Twitter limits (150 requests a day, $20 rebilling limit).

## Constraints

- **Data rules**, carried over from the bot tracker's CLAUDE.md: store timestamps and aggregate counts only; collectors may read post text in memory to compute aggregates; never store or log usernames, account IDs or post text. Exception, approved by Emma on 16 November 2026: a short hand-picked list of named public figures (public role or public brand, never private individuals) may be counted by name, counts only, each with a reason and a checked source; nothing about accounts that reply to, follow or repost them.
- **Precision checks** read posts in memory or in the session; usernames and links are stripped, the text is deleted after coding, and only tallies are kept.
- **Sources**: every term needs a source checked on the original page; every event needs a source and a status. Agent research is spot-checked before it is cited.
- **Naming**: always "Twitter", never "X".
- **Twitter budget**: one Twitter account serves both projects. Both read and write one shared request counter so their combined use stays under the daily cap. Recent counts cost $0.005 a request, full-archive counts $0.010, post reads $0.005 a post.
- **Design system**: the terminal design system (`terminal-design-system/`, canonical copy in the bot tracker repo, also used by Weather Terminal and the retro speed test). Border radius 0, every number labelled, unknown values as `—`. Any change to its rules goes into DESIGN_GUIDE.md and is synced to the other repos.
- **Stack**: Python with httpx and SQLite, as in the bot tracker. No new runtime dependency without a good reason.

## Approaches considered

1. **All code in the new repo** (chosen by Emma, 17 November 2026). Copy only what this project needs from the bot tracker, run it on its own, and share only the Twitter request counter. Fully separate; the collectors can drift from the bot tracker's over time.
2. **Engine in the bot tracker, site published to the new repo.** Less copying and one collector, but the project would not be separate in the code.
3. **New repo that installs the bot tracker as a package.** Clean sharing, but the tracker is not built as a library (fixed paths, one config folder) and would need a refactor first.

## What Emma decided

- Separate repo and site; the bot tracker keeps its original anti-trans terms (troon(s), "no such thing as (a) trans", "you will never be a (real) woman") and the UK single-sex framing in its strikes study. The 13 terms added on 16 November, and the edits to the bot tracker's site that describe them, move to this project only.
- Look: the existing **Broadcast 8s** palette, dark and light modes (light liked best). The trans-flag palette was rejected as hard to read in charts.
- Graphics first; both public and research audiences.
- Studies around events, as in the bot tracker: 14 days before and after the event, a 21-day reference period before that, frozen versions.
- Terms: every candidate at 70% or more hand-checked precision. Two families: **anti-trans** (slurs and memes) and **framing** (phrases news, legal and policy discussion also use).
- Named public figures may be tracked (CLAUDE.md exception above).
- Threads keyword search: approved in principle; waits on Emma's Meta developer app and `threads_keyword_search` approval.
- Meta Ad Library: wanted; waits on Emma's identity confirmation and token.

## The measure

### Terms at launch

Anti-trans: troon(s); tranny; "you will never be a (real) woman" / YWNBAW; "no such thing as (a) trans"; "trans identified male"; autogynephilia; womanface; Trantifa.

Framing: transgenderism; trans/transgender ideology; "trans agenda"; "biological male/man"; "adult human female"; "men in women's sports"; "child mutilation"; "transing kids"; "single-sex spaces"; "single-sex services".

Queries, sources, volumes and precision for each are in the bot tracker's `config/sources.toml`, `docs/NARRATIVES.md` and `docs/research/precision-2026-11-16.json`. Held: "trans cult" (86% precision, source not yet checked). Rejected below 70%: "gender ideology", groomer, "super straight", "gender critical", "social contagion", "trans shooter", the pooled rare search. "Trans youth" is a topic term, not hostility: keep it as a context series, outside both families **(Claude's call)**.

The single-sex phrases have not been precision-checked; check them before the framing family's headline is published **(Claude's call)**.

### Composite (proposed from the research agent's report; approved by Emma on 17 November 2026)

- **Headline per family**: one combined OR query per family through the counts endpoint, so a post matching several terms counts once. Family and probe queries always use the full-archive endpoint, whose limit is 1,024 characters (the recent endpoint allows only 512). If adding a term pushes a family past the limit, loading the config fails with the family's name and length rather than truncating; the family is then split by hand **(Claude's call: both families fit today, so automatic splitting is not built)**.
- **Probe normalisation**: each family count is divided by a common-word probe series ("thing" OR "any" OR "tell", same language and retweet filters), as in Hickey et al. (PLOS ONE 2025), so platform-wide surges such as election night do not look like hate.
- **Index**: the bot tracker's weekday-hour index (each hour against the same weekday and hour 1 to 3 weeks earlier, 100 = normal) with its normal band.
- **Breadth index** (secondary): each term's probe-normalised rate standardised over the reference window, averaged with equal weight and rescaled to 100 (the Economic Policy Uncertainty index method), to show whether a rise is one term or many.
- **Per-term panel**: each term's own index, with its precision and interval beside it.
- **Robustness** reported with every event finding: leave one term out, pooled vs equal-weight, with and without probe normalisation, originals vs reposts, placebo dates.
- The midterms data was already seen before the method was fixed; the methods page says so. For future events the method is registered before the event.

## The site

Static site on GitHub Pages from this repo. Pages, in order of priority:

1. **Study page** (the main page). Header band and data date; a hero number with its label; the headline chart (family index vs normal, event marked, normal band shaded, at most four lines); small multiples, one per term on one shared scale, each printing before / event day / after; a named-figures strip; a "data for researchers" row (CSV, JSON, cite, methods, queries). This is the mockup Emma chose on 16 November 2026 (palette A, with its light mode).
2. **Terms**: every term with its family, query, source link, volume, precision and interval, and why rejected terms were rejected.
3. **Methods**: collection, index, composite, precision checks, robustness, what a count cannot show.
4. **Context**: the 2026 anti-trans ad campaign (bot tracker `docs/MIDTERM-ADS.md`), clearly separated from our own measurements.
5. **Data**: downloads and citation.

Every chart: section label with unit, direct labels, caption naming the baseline and band, a "show data as a table" view, an accessible name, dark and light mode.

## Data

- **Starting data**: copy the existing hourly points for the trans series from the bot tracker's `data/tracker.db` (aggregate counts only): the 3 original anti-trans terms and "trans youth" from late August, the single-sex phrases from late August and 2 November, and the 13 new terms from 17 September. No re-fetching.
- **Collection** (Emma, 17 November 2026): pause between events, like the bot tracker. Once a study's window has closed and its data is in, the study is frozen and collection stops; it resumes when a news check finds an event that fits the research, which opens a new study. While collecting: Twitter counts only, once a day, 3 requests per term plus the probe and the two family queries, about 51 requests a pass (~$0.26) for 16 terms. The shared request counter keeps both projects under the cap together.
- **Later sources**: Threads keyword search (hourly windows, at most 100 results a request, 2,200 queries a day; sensitive keywords return nothing, so slurs may be uncountable there); Meta Ad Library (spend and impression ranges, reach by age, gender and region, US political and issue ads matching the terms); named public figures (counts of their posts matching the terms and their total posts).

## Calls made after the builder check (Claude's calls unless marked)

- **No burst request.** The per-minute "busiest 5 minutes" measure is a coordination signal for the bot tracker, a non-goal here. Each term costs 3 requests a pass (originals, reposts, replies), not 4.
- **Each project collects its own copy** of the three terms they share, so neither depends on the other's schedule. The shared request counter (an environment variable naming one file, read by both projects' budget code) is the only coupling; the bot tracker's `_Budget` gains the same variable.
- **Single-sex phrases are left out** of this site's framing family: they are UK Equality Act wording, not US rhetoric, and they have no precision check. They can come back after a check.
- **Named public figures are not part of the launch.** The study page shows the strip only once at least one figure is configured and has data. Musk and "TransFails" had 0 term matches from 10 to 15 November, so a strip now would be zeros.
- **New history is fetched where the headline needs it** (approved by Emma on 17 November 2026, about 48 requests, ~$0.48): the probe and the two family queries from 8 September, and the 13 newer terms from 8 to 17 September, so every hour of the midterms reference period has its full 1-to-3-week comparison. This replaces "no re-fetching" above for those series only; the existing points are still copied, not re-fetched.
- **The bot tracker is committed first** (Emma, 17 November 2026): its earlier pending work, then the 16 November term edits, as two commits, before the 13 terms are moved out.

## Left to the builder

- Which bot tracker modules to copy and how to trim them (likely `config`, `db`, `collectors/x`, the index code in `analysis`, `study`, `static`), and the page code.
- File layout, command names, tests, and how the shared request counter is located (for example an environment variable pointing at one file).
- Exact chart markup, as long as it follows DESIGN_GUIDE.md §11 and the chosen mockup.
- How to move the 13 terms and the "FRAMING" label edits out of the bot tracker without changing its published findings.
