# Evaluation

`yt-eval` scores the edit, chapter and Shorts tools against labelled transcripts. It exists
so that claims about accuracy rest on numbers, and so that any change in a tool's behaviour
shows up as a reviewed change to a pinned baseline.

```bash
yt-eval datasets/synthetic-v1/dataset.json
```

```bash
yt-eval datasets/synthetic-words-v1/dataset.json --hold-review
```

## Read this first

The only dataset in the repository is **synthetic**. Its transcripts are scripted talks and its
labels come from the script, so they are exact. That makes it a good regression test and a good
way to expose known blind spots. **It says nothing reliable about accuracy on real recordings.**
Real numbers need real, consented transcripts with labels from a human editor (see "Adding a
real dataset" below).

## Metrics

| Task | Metric | Match rule |
| --- | --- | --- |
| Cuts (deadair) | precision/recall **by seconds** | seconds of the tool's merged cuts that are also labelled cut, and the reverse |
| Cuts (deadair) | precision/recall **by event** | a predicted cut matches a labelled cut when IoU >= 0.5, one-to-one |
| Cuts (deadair) | recall by kind | DEAD, FILLER, REPEAT separately |
| Cuts (deadair) | **keep regions cut** | seconds the tool would remove from regions labelled "keep" (for example a pause for emphasis). Lower is better; this is the harm metric |
| Chapters | boundary precision/recall | a boundary matches within +/-3 s, one-to-one; the mandatory 0:00 is excluded |
| Shorts | span precision/recall | a candidate hits a labelled Short when IoU >= 0.5 |

Totals are micro-averaged: counts are summed across cases before dividing.

## A second caution: the defaults below were set by the same author as the data

The review threshold (pauses under 1.5 s are marked `[review]`) and the automatic chapter count
(about one chapter per 90 s) were chosen while knowing these scripted talks: keep-pauses of
1.0-1.3 s, real dead air of 1.6 s or more, three sections in about two minutes. So the perfect
chapter score and the zero "keep regions cut" under `--hold-review` show that **the mechanisms
work as intended**, not that **the thresholds are right**. Only a real labelled set can say that.

## Baseline: `synthetic-v1`, default settings

4 cases: two scripted talks of about 2 minutes, each rendered as clean one-cue-per-utterance
captions and as auto-caption-style chunks (lower case, no punctuation, 7-word cues that linger and
overlap). Per talk: 7 labelled cuts (3 dead air, 3 fillers including one inside a sentence for the
essay, 1 aborted take), 1-2 keep pauses, 2 chapter boundaries, 1-2 labelled Shorts.

```
  tutorial-clean   cuts t-F1 0.93 ev-F1 0.88 keep-cut 1.2s  chapters 2/2 found, 5 proposed  shorts 2/2 found, 2/3 hits
  tutorial-auto    cuts t-F1 0.66 ev-F1 0.50 keep-cut 0.9s  chapters 2/2 found, 6 proposed  shorts 2/2 found, 2/3 hits
  essay-clean      cuts t-F1 0.93 ev-F1 0.86 keep-cut 0.8s  chapters 2/2 found, 4 proposed  shorts 1/1 found, 1/2 hits
  essay-auto       cuts t-F1 0.65 ev-F1 0.55 keep-cut 0.7s  chapters 2/2 found, 4 proposed  shorts 1/1 found, 1/2 hits

  OVERALL (micro-averaged)
    cuts, by seconds      P 0.89  R 0.74  F1 0.81
    cuts, by event        P 0.76  R 0.68  F1 0.72
    recall by kind        DEAD 1.00  FILLER 0.42  REPEAT 0.50
    keep regions cut      3.65s of 6.80s
    chapter boundaries    P 1.00  R 1.00  F1 1.00   (+/-3.0s)
    shorts candidates     P 0.60  R 1.00  F1 0.75   (IoU >= 0.5)
```

(Chapters were P 0.42 / F1 0.59 at the old fixed `--target 7`; the default is now derived from
length - see the caution above.)

With `--hold-review` (pauses under 1.5 s are held back for a human):

```
    cuts, by seconds      P 1.00  R 0.72  F1 0.84
    cuts, by event        P 1.00  R 0.64  F1 0.78
    recall by kind        DEAD 0.92  FILLER 0.42  REPEAT 0.50
    keep regions cut      0.00s of 6.80s
```

Holding back costs recall on auto-captions: their lingering cues shrink a real 1.6 s gap below
1.5 s, so it is held too (DEAD recall 1.00 -> 0.92). That trade-off was not designed in.

The full per-case output is pinned in `datasets/synthetic-v1/baseline.json`, and
`tests/test_evaluation.py::test_results_match_pinned_baseline` fails if a code change moves any
number.

## What the baseline shows

1. **Dead air is found reliably on clean captions** (recall 1.00), but every pause longer than
   the floor is cut, **including pauses kept on purpose** (now marked `[review]` when under 1.5 s). Every dead-air false positive in the
   set is an emphasis pause, and 3.65 s of the 6.8 s labelled "keep" would be removed. A
   transcript cannot tell a dramatic pause from dead air, so a human must review DEAD cuts.
2. **Auto-captions roughly halve the edit quality** (event F1 about 0.5 against about 0.87 on
   clean captions). Overlapping chunks hide pauses shorter than about 0.35 s, and fillers and
   aborted takes are merged into neighbouring speech, so cue-level detection cannot see them. Use
   a word-timed transcript (Whisper with word timestamps, or a clean SRT) for editing.
3. **Fillers inside a sentence are never cut from cue-level transcripts** (FILLER recall 0.42).
   With word timings they are - see `synthetic-words-v1` below.
4. **Restarts are found on clean captions and missed on auto-captions** (REPEAT 0.50: 2 of 4).
5. **Rhetorical repetition was not mistaken for a retake** ("Every single time we changed..." /
   "Every single time we held..."), because the five-word openings differ.
6. **Chapters found every real boundary but over-proposed at the old fixed `--target 7`**
   (precision 0.42). The default is now derived from the video's length; set `--target` to the
   number of sections you actually have when you know it.
7. **Shorts**: every labelled Short is in the top 5. About 2 in 5 candidates are spans a human
   did not mark. That is acceptable for a shortlist, not for auto-cutting.

## `synthetic-words-v1`: the same talks with word timings

Same scripts and labels, rendered as Whisper JSON with exact word times and as YouTube-style
rolling auto-captions with inline word start tags.

```
  tutorial-whisper   cuts t-F1 0.90 ev-F1 0.88 keep-cut 1.6s  chapters 2/2 found, 2 proposed  shorts 2/2 found, 2/3 hits
  tutorial-youtube   cuts t-F1 0.21 ev-F1 0.44 keep-cut 0.0s  chapters 0/2 found, 2 proposed  shorts 2/2 found, 2/2 hits
  essay-whisper      cuts t-F1 0.93 ev-F1 0.93 keep-cut 1.1s  chapters 2/2 found, 2 proposed  shorts 1/1 found, 1/2 hits
  essay-youtube      cuts t-F1 0.17 ev-F1 0.44 keep-cut 0.0s  chapters 0/2 found, 2 proposed  shorts 0/1 found, 0/2 hits

  OVERALL (micro-averaged)
    cuts, by seconds      P 0.84  R 0.55  F1 0.66
    cuts, by event        P 0.86  R 0.64  F1 0.73
    recall by kind        DEAD 0.50  FILLER 0.83  REPEAT 0.50
    keep regions cut      2.65s of 6.80s
    chapter boundaries    P 0.50  R 0.50  F1 0.50   (+/-3.0s)
    shorts candidates     P 0.56  R 0.83  F1 0.67   (IoU >= 0.5)
```

- **Whisper word timings fix the inline-filler blind spot**: every filler in the Whisper cases is
  found, including "so the, um, real problem" (FILLER recall 0.83 overall, all misses on the
  YouTube cases).
- Word-gap dead air removes a little more of the deliberate pauses than cue gaps do (1.6 s vs
  1.2 s on the tutorial), because a gap measured between words includes the breath after an
  utterance's last word.
- **The YouTube rows rest on an unverified model.** The generator assumes each caption line stays
  on screen until the next starts, so pauses are invisible at cue level and the tags give word
  starts only. Under that model, dead air and chapter boundaries (which come from pauses)
  disappear. A real auto-caption file could not be fetched to check this in the environment
  where it was written. If the model is right, the practical advice is: **transcribe with
  Whisper (word timestamps on) for editing and chapters; do not rely on YouTube's own captions.**

## Adding a real dataset

1. Use transcripts you have the right to use (your own channel, or with written consent). Do
   not commit personal data you are not allowed to publish. Keep private sets outside the repo
   and point `yt-eval` at them.
2. Have an editor label, in seconds: what they would cut (`cuts`, with `kind`), pauses they would
   keep (`keep`), section starts (`chapters`) and good Shorts (`shorts`). Label without looking at
   the tools' output.
3. Write `dataset.json` in the format documented in `youtube_intelligence/evaluation/dataset.py`
   with `"synthetic": false`.
4. Report the numbers with the dataset's size and source. A handful of videos is an anecdote.

## Regenerating the synthetic sets

```bash
python datasets/synthetic-v1/generate.py
```

```bash
python datasets/synthetic-words-v1/generate.py
```

The generator does not import the engine, and a test enforces that, so its labels cannot leak
from tool output. A test also checks that regenerating gives byte-identical files.
