# Tool review (0.1.0)

A review of each upstream tool at `a2feb21`: what it measures, where it misleads, and what changed.
Defects and fixes are listed in [CHANGELOG.md](../CHANGELOG.md). This page covers the judgement calls.

## hookscore: a heuristic, not a predictor

**What it is.** Five sub-scores (SPECIFICITY, ADDRESS, STAKES, CURIOSITY, BREVITY), each a
clamped linear function of regex and word-list counts. The verdict is `0.6 x mean + 0.4 x min`.

**What it is not.** It has no knowledge of the topic, the audience, the delivery, the
thumbnail or the platform. It does not and cannot predict views, retention or virality. Upstream's
own evaluation (74 real hooks, five channels) found it separates deliberately bad hooks from real
ones well, and separates a creator's own hits from misses "barely at all".

**Ways it can be gamed** (documented and pinned by `test_documented_gaming_behaviour_is_real`):
- every number adds 22 to SPECIFICITY, so figures raise the score whether or not they are true;
- every "you" adds 20 to ADDRESS;
- fear words ("lose", "fail", "die") add 26 each to STAKES;
- "actually" counts as filler (SPECIFICITY) and as curiosity (CURIOSITY).

**Formula classifier.** Matching each of the 21 library examples against the library itself, 13 of
21 classify as their own formula. The other 8 come out Unclassified or as a neighbour, for example
The Mistake's own example is Unclassified (`test_formula_self_classification_rate_is_as_documented`).
Treat formula names as a rough tag.

**Decision.** Weights are unchanged, so scores stay comparable with upstream's calibration
(golden-tested). The limits are stated in the docstring, in the text output, and in the
`/yt-script` skill addition.

## title: stop rewarding numbers, start flagging claims

Upstream treated "no number, date or name" as an issue (−14) and any digit as a strength (+4),
an 18-point swing for typing a digit. It checked only for digits, so names and dates never
counted. The tool cannot know whether a number is true, so it ended up rewarding invented
numbers, which the skills themselves forbid ("Never invent a number").

Changes: the number check is advisory only; claim language and number-stuffing are scored issues.
The claim patterns are a short, conservative list (guarantees, absolutes, instant results, income
claims, conspiracy hooks). They will miss things and occasionally over-flag, so treat a `claim`
as a prompt to check that the video shows proof. The 60 and 40-character truncation points are
observed display widths that change with device and layout. Only the 100-character maximum is a
hard YouTube rule.

## retention: descriptive, with stated limits

The arithmetic is unchanged. What a reader should not infer:
- **Sample size.** On a low-view video a 5-point "cliff" can be a handful of viewers. The export
  carries no view count, so the tool cannot warn automatically. Check views in Studio.
- **Video age.** A video's first days are dominated by subscribers. Compare curves at similar ages.
- **Format.** The healthy / leaking / severe bands (25 / 40 points) are long-form rules of thumb.
  They do not transfer to Shorts, music, or videos shorter than about a minute, where 30 seconds is
  most of the video.
- **Audience mix.** A curve averages traffic sources, devices and countries.
- **Rewatches** push absolute retention above 100% or upward. Upward moves are never cliffs.
- `slide_per_unit` is per second on a seconds axis and per 1% of the video on a percent axis.
  The text report now names the unit.

## deadair and chapters

Both rely on caption timing. Auto-captions are often split mid-sentence and overlap, which is why
the interval union and the latest-end gap rule matter. Chapters picks boundaries from pauses and
vocabulary shift. Its draft titles are topic words for a human to rewrite.

## swipe (outliers)

Multiple-over-own-median is the right normaliser for channel size. It does not adjust for video
age, upload date or Shorts mixed with long-form. Collect comparable windows. Four videos per
channel is the minimum to compute anything, not a statistically comfortable sample.

## moments (new)

Each sentence's "extra loss" is the audience lost while it was said, minus the video's typical
(median) loss rate across its middle. Two limits follow from that design. First, it is correlation:
a sponsor read placed where viewers would leave anyway looks costly. Second, whatever kind of
sentence fills most of a video becomes the typical rate and cannot stand out; on the invented demo
set, signposts were scripted to hold viewers and measure as "no clear effect". The first 30 s and
last 10% are skipped, and a type needs 3+ occurrences across 2+ videos before it is called a
pattern. The demo data is scripted, so recovering its effects shows the arithmetic works, not that
real audiences behave this way.

## shorts (new)

Surface signals only: pauses, punctuation, connective first words, contrast words. Without
punctuation (raw auto-captions) only the pause signals work. It produces a shortlist, not a decision.
