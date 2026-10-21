"""Renders one synthetic clip through the handler and checks the image.

Run inside the built image, as CI does, as an unprivileged user with a
root-owned empty /tmp and the CPU and memory of the deployed tier, which is
how Lambda runs it. The clip is AAC in MPEG-TS like a real segment, read
through a file:// URL so nothing outside the container is touched.
"""

import struct
import subprocess
import sys
import time

import app

CLIP = "/tmp/smoke.ts"
SECONDS = 10
SAMPLE_RATE = 48000

subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
     f"anoisesrc=d={SECONDS}:c=pink:r={SAMPLE_RATE}", "-ac", "1", "-c:a", "aac", "-f", "mpegts", CLIP],
    check=True,
)

captured = {}
app.store_image = lambda job, png: captured.update(png=png)

t0 = time.time()
result = app.lambda_handler({"audio_url": f"file://{CLIP}", "image_url": None}, None)
elapsed = time.time() - t0

png = captured["png"]
if png[:8] != b"\x89PNG\r\n\x1a\n":
    sys.exit("output is not a PNG")
width, height = struct.unpack(">II", png[16:24])
expected_width = 1 + int(result["sample_rate"] * SECONDS) // app.DEFAULTS["hop_length"]

print(f"rendered {width}x{height} in {elapsed:.1f}s, {len(png)} bytes, sample rate {result['sample_rate']}")

if height != app.DEFAULTS["n_fft"] // 2:
    sys.exit(f"height {height}, expected {app.DEFAULTS['n_fft'] // 2}")
# AAC pads the clip by up to a couple of frames, so allow a few columns.
if abs(width - expected_width) > 8:
    sys.exit(f"width {width}, expected about {expected_width}")
if result["image_size"] != len(png):
    sys.exit(f"image_size {result['image_size']} does not match the {len(png)} bytes rendered")
