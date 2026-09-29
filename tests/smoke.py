"""Renders one clip in a fresh container and reports how long each step took.

Run inside the built image, the way CI does, to rehearse a Lambda cold start:
an unprivileged user, a root-owned empty /tmp, and the CPU and memory of the
deployed tier. The clip is AAC in MPEG-TS like a real segment. The render
skips S3 both ways, as in warm.py.

Fails if the first render is slow enough to suggest the caches were not
restored, or if the two renders disagree about the image.
"""

import subprocess
import sys
import time

CLIP = "smoke.ts"
JOB = {
    "id": CLIP,
    "audio_bucket": "none",
    "audio_key": "none",
    "sample_rate": None,
    "image_key": None,
    "image_bucket": None,
}
# A cold render without the caches took over 30 s at this CPU share.
SLOW_FIRST_RENDER = 15.0

subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
     "anoisesrc=d=10:c=pink:r=48000", "-ac", "1", "-c:a", "aac", "-f", "mpegts", f"/tmp/{CLIP}"],
    check=True,
)

t0 = time.time()
import app  # noqa: E402  (timed on purpose: this is where the caches are restored)

t1 = time.time()
first = app.make_spectrogram(JOB)
t2 = time.time()
second = app.make_spectrogram(JOB)
t3 = time.time()

print(f"import {t1 - t0:.1f}s | first render {t2 - t1:.1f}s | second render {t3 - t2:.1f}s | image {first['image_size']} bytes")

if first["image_size"] != second["image_size"]:
    sys.exit(f"renders differ: {first['image_size']} vs {second['image_size']} bytes")
if t2 - t1 > SLOW_FIRST_RENDER:
    sys.exit(f"first render took {t2 - t1:.1f}s; were the caches restored?")
