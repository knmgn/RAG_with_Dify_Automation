# Demo Video Assets

The shooting script itself lives in Chapter 6 of the design doc,
[`../02_dify_chatflow_design.md`](../02_dify_chatflow_design.md).
This directory holds only the files you can drop straight into an editor.

| File | Purpose |
|---|---|
| `demo_captions.srt` | English captions, one line per cue |

## Using the captions

### Burn them in (recommended)

Premiere Pro, DaVinci Resolve and Final Cut Pro all import SRT directly. Place the captions at the
bottom center on a semi-transparent black band (60–70% opacity), at a height where they do not cover
the bot's answer.

> 💡 For portfolio use, **burning in** is recommended. Listing pages on Upwork and similar platforms
> often autoplay with sound and captions off, so caption tracks are never shown.

### Uploading as a caption track on YouTube / Vimeo

Upload `demo_captions.srt` as the English caption track. Burned-in captions remain the safer choice
for autoplay previews.

## Timecodes

The timings in `demo_captions.srt` are the values planned in the script.
Drag each clip in your editor to match the length of the actual recording.

Shot 1 (0:00–0:08) assumes a file-request response time of about 1.7 seconds, measured on the
Japanese edition (tag `v1-ja`). English answers are longer, so re-check the timings against your
recording, and move the switch between captions 1 and 2 to when the answer actually appears.
