"""Renders one spectrogram image from one audio segment, with ffmpeg.

The request says where to read the audio and where to write the image, as
URLs; the function knows nothing about what is behind them. Render
parameters are explicit, with the defaults orcasite has always used, and
the response echoes the ones that were applied.

    {
      "audio_url": "https://... (presigned GET)",
      "image_url": "https://... (presigned PUT), or null to render and discard",
      "parameters": {"fmax": 15000, "format": "webp", ...}   # optional, see DEFAULTS
    }

`format` is "png" or "webp". A WebP tile is about a fifth the size of the
PNG at the default `quality` of 80, with no visible difference at the size
the timeline draws it; `quality` 100 makes it lossless, at about three fifths
of the PNG. `quality` has no effect on PNG, which is always lossless.

For one release the previous shape is also accepted: `audio_bucket` and
`audio_key`, `image_bucket` and `image_key`, read and written with boto3.
"""

import os
import subprocess
import tempfile
import urllib.request
import wave

DEFAULTS = {
    "n_fft": 1024,
    "hop_length": 256,
    "fmin": 1,
    "fmax": 15000,
    "db_min": 10,
    "db_max": 80,
    "cmap": "viridis",
    "frequency_scale": "linear",
    "format": "png",
    "quality": 80,
}

CONTENT_TYPES = {"png": "image/png", "webp": "image/webp"}

# ffmpeg's dB scale is relative to full scale, while the dB window orcasite's
# images were drawn with is relative to an amplitude of 0.01 in librosa's
# STFT. This offset lines the two up: it was fitted against a production
# image, whose luminance distribution it reproduces to within 0.01.
DB_OFFSET = -122

FSCALE = {"linear": "lin", "log": "log"}


def lambda_handler(event, context):
    return {"status": 200, **make_spectrogram(event)}


def make_spectrogram(job):
    params = {**DEFAULTS, **(job.get("parameters") or {})}

    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        audio_path = os.path.join(tmp, "audio")
        wav_path = os.path.join(tmp, "audio.wav")
        fetch_audio(job, audio_path)
        sample_rate, samples = decode(audio_path, wav_path)
        width = 1 + samples // params["hop_length"]
        height = params["n_fft"] // 2
        image = render(wav_path, params, width, height)

    content_type = CONTENT_TYPES[params["format"]]
    store_image(job, image, content_type)

    return {
        "image_size": len(image),
        "content_type": content_type,
        "sample_rate": sample_rate,
        "width": width,
        "height": height,
        "parameters": params,
        # The names orcasite has stored since the first renderer.
        "frequency_spacing": params["frequency_scale"],
        "freq_min": params["fmin"],
        "freq_max": params["fmax"],
        "color_map": params["cmap"],
    }


def render(audio_path, params, width, height):
    """One ffmpeg invocation: spectrogram as intensity, then the colour map.

    showspectrumpic's own colour maps start at black, so the image is drawn
    in grey and matplotlib's ramp applied with pseudocolor, which carries the
    same tables. Its window size follows from the height (n_fft/2 bins).
    """
    spectrum = ":".join(
        [
            f"s={width}x{height}",
            "mode=combined",
            "color=intensity",
            "scale=log",
            f"fscale={FSCALE[params['frequency_scale']]}",
            "win_func=hann",
            f"start={params['fmin']}",
            f"stop={params['fmax']}",
            f"limit={params['db_max'] + DB_OFFSET}",
            f"drange={params['db_max'] - params['db_min']}",
            "legend=0",
        ]
    )
    graph = f"showspectrumpic={spectrum},format=gbrp,pseudocolor=preset={params['cmap']}"
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", audio_path,
         "-lavfi", graph, "-f", "image2pipe", *encoder(params), "-"],
        check=True,
        capture_output=True,
    ).stdout


def encoder(params):
    """The ffmpeg output options for the requested image format.

    libwebp's default effort level is kept: level 6 saved another 8% of a
    tile for a tenth of a second more at Lambda's CPU share, and lossless
    output is the same size at every level.
    """
    if params["format"] == "png":
        return ["-c:v", "png"]
    if params["format"] == "webp":
        if params["quality"] >= 100:
            return ["-c:v", "libwebp", "-lossless", "1"]
        return ["-c:v", "libwebp", "-quality", str(params["quality"])]
    raise ValueError(f"unknown image format {params['format']!r}; expected one of {sorted(CONTENT_TYPES)}")


def decode(audio_path, wav_path):
    """Decodes the segment to WAV and returns its sample rate and length.

    The image is sized from the samples actually decoded: the container's
    duration undercounts an AAC stream by a frame or two, which would make
    each tile a few pixels narrower than the archive's.
    """
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", audio_path, "-f", "wav", wav_path],
        check=True,
        capture_output=True,
    )
    with wave.open(wav_path, "rb") as wav:
        return wav.getframerate(), wav.getnframes()


def fetch_audio(job, path):
    if job.get("audio_url"):
        with urllib.request.urlopen(job["audio_url"]) as response, open(path, "wb") as file:
            file.write(response.read())
    else:
        import boto3

        boto3.client("s3").download_file(job["audio_bucket"], job["audio_key"].lstrip("/"), path)


def store_image(job, image, content_type):
    if job.get("image_url"):
        request = urllib.request.Request(
            job["image_url"], data=image, method="PUT", headers={"Content-Type": content_type}
        )
        with urllib.request.urlopen(request):
            pass
    elif job.get("image_bucket") and job.get("image_key"):
        import boto3

        boto3.client("s3").put_object(
            Bucket=job["image_bucket"], Key=job["image_key"].lstrip("/"), Body=image, ContentType=content_type
        )
