"""Renders one spectrogram PNG from one audio segment, with ffmpeg.

The request says where to read the audio and where to write the image, as
URLs; the function knows nothing about what is behind them. Render
parameters are explicit, with the defaults orcasite has always used, and
the response echoes the ones that were applied.

    {
      "audio_url": "https://... (presigned GET)",
      "image_url": "https://... (presigned PUT), or null to render and discard",
      "parameters": {"fmax": 15000, ...}   # optional, see DEFAULTS
    }

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
}

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
        png = render(wav_path, params, width, height)

    store_image(job, png)

    return {
        "image_size": len(png),
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
         "-lavfi", graph, "-f", "image2pipe", "-c:v", "png", "-"],
        check=True,
        capture_output=True,
    ).stdout


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


def store_image(job, png):
    if job.get("image_url"):
        request = urllib.request.Request(
            job["image_url"], data=png, method="PUT", headers={"Content-Type": "image/png"}
        )
        with urllib.request.urlopen(request):
            pass
    elif job.get("image_bucket") and job.get("image_key"):
        import boto3

        boto3.client("s3").put_object(
            Bucket=job["image_bucket"], Key=job["image_key"].lstrip("/"), Body=png, ContentType="image/png"
        )
