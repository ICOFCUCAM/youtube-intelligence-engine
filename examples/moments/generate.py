"""Generate the invented demo set for yt-moments: 3 videos, each a transcript and a retention export.

    python examples/moments/generate.py [out_dir]

The talks and the audience are INVENTED. Each segment of speech carries a scripted extra loss
(percentage points) that the retention curve then contains, so the demo shows the mechanism:
sponsor reads and tangents cost viewers here because this script says so. It proves nothing
about real audiences. Does not import the engine.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDE = 0.035          # baseline points lost per second in the middle of a video
HOOK = 22.0            # points lost in the first 30 s

# (text, seconds, extra points lost while it is said)
VIDEOS = {
    "vid-hooks": ("Why your hooks fail", [
        ("Your first fifteen seconds decide whether anyone stays.", 6, 0),
        ("Most openings summarise instead of asking a question.", 8, 0),
        ("Here is the structure I use for every opening line.", 16, 0),
        ("Step one: confirm the title in the first sentence.", 30, -0.4),
        ("This video is sponsored by Brightdesk, use code HOOKS for twenty percent off.", 28, 3.2),
        ("Step two: open a gap the viewer cannot close.", 34, -0.3),
        ("Quick story, the first time I filmed I forgot to press record.", 26, 2.1),
        ("Step three: prove the payoff exists before the first minute.", 40, -0.4),
        ("If this helped, subscribe and turn on notifications.", 12, 1.4),
        ("Next, the three words that kill a hook.", 36, -0.2),
        ("As I said earlier, confirm the title first.", 20, 0.9),
        ("That is the whole system. Go and rewrite one opening today.", 30, 0),
    ]),
    "vid-thumbs": ("Thumbnails at feed size", [
        ("Your thumbnail is judged at the size of a postage stamp.", 7, 0),
        ("So that is the size you should design it at.", 9, 0),
        ("Let me show you exactly what survives at feed size.", 15, 0),
        ("Number one: three words is the ceiling.", 32, -0.3),
        ("By the way, my camera is back from repair, more on that another day.", 24, 1.8),
        ("Number two: never repeat the words in the title.", 30, -0.4),
        ("Today's video is brought to you by Pixelgrid, link in the description.", 30, 3.6),
        ("Number three: contrast beats colour at small sizes.", 38, -0.2),
        ("Before we go on, a quick reminder to like the video.", 14, 1.2),
        ("Moving on to faces and expressions.", 34, -0.3),
        ("Shrink it, check it, then choose it.", 28, 0),
    ]),
    "vid-retention": ("Reading your retention graph", [
        ("The retention graph is the only honest feedback you get.", 8, 0),
        ("Almost nobody exports it, and that is a mistake.", 7, 0),
        ("Here is how to read it in five minutes.", 15, 0),
        ("First, find the hook leak in the first thirty seconds.", 36, -0.3),
        ("Fun fact, the first video I ever uploaded had nine views.", 22, 1.9),
        ("Second, look for single steep cliffs.", 32, -0.4),
        ("Thanks to Ledgerly for sponsoring this video, try it free with my link.", 26, 3.0),
        ("Third, measure the slow slide across the middle.", 40, -0.2),
        ("To recap, hook leak, cliffs, then the slide.", 22, 0.8),
        ("Don't forget to subscribe if you want part two.", 12, 1.5),
        ("Fix the biggest leak first and ignore the rest this week.", 30, 0),
    ]),
}


def ts(x):
    h, r = divmod(x, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def build(vid, segments, out):
    t, cues, extra_at = 0.0, [], []
    for text, sec, extra in segments:
        cues.append((t, t + sec - 0.3, text))
        extra_at.append((t, t + sec, extra))
        t += sec
    dur = t

    def lost_by(x):
        hook = HOOK * min(x, 30.0) / 30.0
        slide = SLIDE * max(0.0, x - 30.0)
        extra = sum(e * max(0.0, min(x, b) - a) / (b - a) for a, b, e in extra_at)
        return hook + slide + extra

    with open(os.path.join(out, f"{vid}.srt"), "w") as f:
        for n, (a, b, text) in enumerate(cues, 1):
            f.write(f"{n}\n{ts(a)} --> {ts(b)}\n{text}\n\n")
    with open(os.path.join(out, f"{vid}-retention.csv"), "w") as f:
        f.write("Video position (%),Absolute audience retention (%)\n")
        for i in range(101):
            f.write(f"{i},{round(100 - lost_by(dur * i / 100), 2)}\n")
    return dur


def main(out=HERE):
    manifest = []
    for vid, (title, segments) in VIDEOS.items():
        dur = build(vid, segments, out)
        manifest.append({"id": vid, "title": title, "transcript": f"{vid}.srt",
                         "retention": f"{vid}-retention.csv", "duration": round(dur, 3)})
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump({"note": "Invented demo data: talks and audience are made up.", "videos": manifest}, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
