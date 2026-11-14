# Examples

All inputs live in [`../tests/fixtures/`](../tests/fixtures/): a synthetic 90-second talk
(`sample.srt`, `.vtt`, Whisper `sample_whisper.json` and array `sample_array.json`), retention
exports on a percent and a seconds axis, a collected-videos list, hooks and titles. Run from the
repository root after `pip install -e .`.

```bash
yt-deadair tests/fixtures/sample.srt
```

```
  tests/fixtures/sample.srt   90.00s in, 24 cues, dead-air floor 0.45s

    FILLER      6.90 ->     7.40    0.50s   um
    DEAD       15.12 ->    16.18    1.05s   1.50s gap
    FILLER     19.90 ->    20.30    0.40s   so yeah
    REPEAT     20.50 ->    24.10    3.60s   restart of "read the hook out loud"
    DEAD       28.82 ->    31.18    2.35s   2.80s gap
    ...
  10 cuts, 14.55s removed, 75.45s out (16.2% shorter)
```

```bash
yt-chapters tests/fixtures/sample_array.json
```

```
  0:00 Open Opening First
  0:16 Read Hook Loud
  0:31 Thumbnail Word Work
  0:47 Contrast Matters More
  1:00 Retention Graphs Show
  1:12 Every Cliff Middle

  6 chapters
```

```bash
yt-retention tests/fixtures/retention_seconds.csv
```

```
  HOOK LEAK   24.0 points lost in the opening   [healthy]
  CLIFFS      the moments people actually left
    - 18.4%  at       4s
    -  9.4%  at      60s
  SLIDE       0.355% per second across the middle
  LIMITS      low view counts make the curve noisy - a cliff can be a handful of people
              ...
```

```bash
yt-retention tests/fixtures/retention_percent.csv --duration 600 --transcript tests/fixtures/sample.srt
```

```bash
yt-title --title "Posting less grew my channel" --thumb "3X VIEWS"
```

```bash
yt-hookscore tests/fixtures/hooks.txt
```

```bash
yt-swipe tests/fixtures/collected.json --min 2.0
```

```bash
yt-shorts tests/fixtures/sample.srt --top 3
```

```bash
python examples/library_usage.py
```

The same commands work without installing, from inside a skill folder, as upstream documented
them, for example `python3 skills/yt-edit/deadair.py tests/fixtures/sample.srt`.
