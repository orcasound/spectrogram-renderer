"""Renders one synthetic clip through the handler, as PNG and as WebP.

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
app.store_image = lambda job, image, content_type: captured.update(image=image, content_type=content_type)


def dimensions(image):
    """Width and height from the file header, or None if the type is unknown."""
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", struct.unpack(">II", image[16:24])
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        if image[12:16] == b"VP8 ":  # lossy: 14-bit dimensions after the frame header
            width, height = struct.unpack("<HH", image[26:30])
            return "image/webp", (width & 0x3FFF, height & 0x3FFF)
        if image[12:16] == b"VP8L":  # lossless: 14-bit dimensions, minus one, packed
            bits = struct.unpack("<I", image[21:25])[0]
            return "image/webp", ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return None, None


def render(parameters):
    t0 = time.time()
    result = app.lambda_handler({"audio_url": f"file://{CLIP}", "image_url": None, "parameters": parameters}, None)
    elapsed = time.time() - t0

    image = captured["image"]
    content_type, size = dimensions(image)
    if content_type is None:
        sys.exit(f"{parameters}: output is not a PNG or WebP")
    if content_type != captured["content_type"] or content_type != result["content_type"]:
        sys.exit(f"{parameters}: a {content_type} image was stored as {captured['content_type']} and reported as {result['content_type']}")
    width, height = size
    expected_width = 1 + int(result["sample_rate"] * SECONDS) // app.DEFAULTS["hop_length"]

    print(f"{parameters or 'defaults'}: {content_type} {width}x{height} in {elapsed:.1f}s, {len(image)} bytes, sample rate {result['sample_rate']}")

    if height != app.DEFAULTS["n_fft"] // 2:
        sys.exit(f"height {height}, expected {app.DEFAULTS['n_fft'] // 2}")
    # AAC pads the clip by up to a couple of frames, so allow a few columns.
    if abs(width - expected_width) > 8:
        sys.exit(f"width {width}, expected about {expected_width}")
    if result["image_size"] != len(image):
        sys.exit(f"image_size {result['image_size']} does not match the {len(image)} bytes rendered")
    return len(image)


png = render({})
webp = render({"format": "webp"})
lossless = render({"format": "webp", "quality": 100})
# Noise is the worst case for a lossy encoder, so on this clip the two WebPs
# come out about the same size; on a real segment the lossy one is a third
# of the lossless one. Both should still beat the PNG.
if not max(webp, lossless) < png:
    sys.exit(f"expected both WebPs ({webp}, {lossless}) to be smaller than the PNG ({png})")
