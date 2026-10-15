# Demo Video Assets

The shooting script itself lives in Chapter 6 of the design doc,
[`../02_dify_chatflow_design.md`](../02_dify_chatflow_design.md).
This directory holds only the files you can drop straight into an editor.

| File | Purpose |
|---|---|
| `demo_captions.srt` | Bilingual captions. Line 1 = Japanese, line 2 = English |

## Using the captions

### Burn them in (recommended)

Premiere Pro, DaVinci Resolve and Final Cut Pro all import SRT directly.
One caveat: **you cannot style the Japanese and English lines differently**.
SRT carries no style information, so both lines look the same.

To style them differently, split the captions into two tracks:

```bash
# Japanese-only and English-only SRT files
awk 'BEGIN{RS="";FS="\n"} {print $1"\n"$2"\n"$3"\n"}' demo_captions.srt > captions_ja.srt
awk 'BEGIN{RS="";FS="\n"} {print $1"\n"$2"\n"$4"\n"}' demo_captions.srt > captions_en.srt
```

Place the Japanese track about 120px from the bottom and the English track about 70px
from the bottom. Setting English at 75–80% of the font size, in a slightly lighter colour,
makes the primary/secondary relationship clear.

### Uploading as caption tracks on YouTube / Vimeo

If you upload caption tracks instead of burning them in, split the file into
`captions_ja.srt` and `captions_en.srt` and **upload one per language**. If you upload
the bilingual file as-is, viewers who pick Japanese captions also get the English line.

> 💡 For portfolio use, **burning in** is recommended. Listing pages on Coconala and Upwork
> often autoplay with sound and captions off, so caption tracks are never shown.

## Timecodes

The timings in `demo_captions.srt` are the values planned in the script.
Drag each clip in your editor to match the length of the actual recording.

Shot 1 (0:00–0:08) in particular assumes the measured response time of 1.7 seconds.
If the recording has a longer pause, move the switch between captions 1 and 2 to when the
answer actually appears on screen.
