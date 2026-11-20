# What drove the rise on 20 October 2026

A one-off check, outside the frozen study. Emma approved up to $2.10 on 20 November 2026. It cost $1.885: 369 posts read at $0.005, plus 4 full-archive count pages at $0.010. It used 44 requests of the shared daily cap.

## The question

On 20 October 2026, four framing terms stepped up at about 13:00 UTC and stayed high until the election. Original posts a day, 19 October then 20 October: "child mutilation" 318 then 620, "men in women's sports" 445 then 709, "transing kids" 152 then 252, "biological male" 677 then 781. Overall Twitter volume (the probe) did not change. News searches found no single event on that day that explains it.

## Method

- **Posts read.** Full-archive search, English original posts (`-is:retweet`), for each of the four terms. On 19 and 20 October, 13:00 to 24:00 UTC, in five slices of 2 to 3 hours, 10 posts per slice: 369 posts in all. Search returns the newest posts in each slice first, so the sample leans to the end of each slice.
- **Privacy.** No author fields were requested. In memory, @mentions were replaced and links removed, keeping only each link's domain. The text was written to a temporary file for coding, then deleted. No post IDs, usernames or post text are kept. This file holds only tallies and paraphrased descriptions; public figures are named.
- **Coding.** Two AI coding agents (Claude subagents), not people, coded the posts: two terms each.
  - Stance: anti-trans use, pushback, neutral or news, another meaning, or unclear.
  - Topic: the race, story or hook the post refers to.
  - Copy: whether the text repeats another post's text word for word, within the same term and day.
- **Per-minute counts.** Full-archive counts at minute granularity, for the four terms, 19 to 21 October.

## Results

| Term · day | Posts coded | Anti-trans use | Pushback | Copied texts |
|---|---|---|---|---|
| child mutilation · 19 Oct | 46 | 36 | 7 | 0 |
| child mutilation · 20 Oct | 47 | 47 | 0 | 8 |
| transing kids · 19 Oct | 48 | 37 | 8 | 0 |
| transing kids · 20 Oct | 46 | 31 | 13 | 5 |
| men in women's sports · 19 Oct | 43 | 36 | 3 | 2 |
| men in women's sports · 20 Oct | 46 | 41 | 2 | 13 |
| biological male · 19 Oct | 42 | 32 | 1 | 0 |
| biological male · 20 Oct | 46 | 37 | 6 | 2 |
| **All four · 19 Oct** | **179** | **141 (79%)** | **19** | **2 (1%)** |
| **All four · 20 Oct** | **185** | **156 (84%)** | **21** | **28 (15%)** |

About four in five posts are replies on both days. The coders returned codes for 364 of the 369 posts; the other 5 are not in the table.

**Copy-pasted text.** On 20 October, 28 of 185 sampled posts repeat another post's exact text, against 2 of 179 on 19 October. Each copy group sits in a single hour:
- **Michigan Senate.** One attack on Abdul El-Sayed, repeated 8 times at 16:00 UTC. It is a list of smears that includes calling him "pro child mutilation".
- **Texas Senate.** One attack on James Talarico's faith and mental state, repeated 6 times at 18:00 UTC. It ends by urging Texans not to vote for him.
- **Generic lists.** Lists of "Democrats'" positions, repeated 3 and 4 times; the second appears at 14:00 and 23:00 UTC. They run sex changes for children together with open borders, DEI and other grievances.
- **Other.** One post about Black voters and the Democratic Party's history, repeated 3 times at 16:00 UTC.

**Topics new on 20 October:**
- **Texas Senate.** Posts about the race rose from 3 to 13 in "men in women's sports", including attacks on Talarico's line "God is nonbinary".
- **WNBA.** In "biological male", 11 posts react to a WNBA statement that only women are eligible, and to claims about two named players.
- **A pastor.** A reply storm targets a pastor who said he voted for Democrats. The replies carry the terms inside long lists of grievances.
- **Mailers.** In "transing kids", posts discuss mailers to Republicans made to look as if they came from LGBTQ groups. Most of these posts say the mailers were fake, which accounts for most of the rise in pushback.
- **Child mutilation.** Every sampled post on 20 October was anti-trans use, against 36 of 46 on 19 October.

**Per-minute counts.**
- On 19 October no term had a minute at five or more times its daily average. On 20 October there were 14 such minutes. Child mutilation had a run of them from 19:55 to 20:04 UTC.
- On 21 October there were 22 such minutes, including runs for child mutilation from 04:16 to 04:39 UTC and for transing kids from 21:13 to 21:18 UTC.
- The four terms do not burst together: on each of the three days, minute-by-minute correlations between terms are between -0.02 and 0.13.

## What this shows and does not show

- **No single news event.** The rise on 20 October has no single news hook. It is a mix of election attacks (Texas and Michigan Senate, generic lists about Democrats), reply storms, and two news stories (the WNBA and the mailers).
- **Copy-pasted replies.** About 15% of sampled posts on 20 October are copy-pasted text, against about 1% the day before, mostly replies posted in tight clusters. That is a known sign of organised or scripted replying.
- **Not proof of coordination across accounts.** Without author data we cannot tell whether a copy group came from one account pasting the same reply many times or from many accounts. Counting distinct authors among the copies would answer this, but it needs author reads ($0.010 per user) and a decision on handling account data in memory.
- **Small samples.** Samples are small (about 45 posts per term and day), slices are weighted to their latest posts, and the coders were AI agents. Treat the percentages as rough.
