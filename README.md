# spectrogram-renderer

A Lambda function that renders one spectrogram PNG from one hydrophone audio segment. [Orcasite](https://github.com/orcasound/orcasite) invokes it by name, once per `AudioImage`, and stores what it answers as the image's parameters. It has no other entry point.

The whole render is one ffmpeg command ([`core/app.py`](core/app.py), `render`): `showspectrumpic` draws the spectrogram as intensity and `pseudocolor` applies matplotlib's colour ramp. The handler around it fetches the audio, probes its sample rate and duration to size the image, and stores the PNG. There is no Python beyond the standard library, so the image is the Lambda base plus a static ffmpeg, and a cold start costs about a second.

## Contract

```json
{
  "audio_url": "https://… (presigned GET)",
  "image_url": "https://… (presigned PUT), or null to render and discard",
  "parameters": {"n_fft": 1024, "hop_length": 256, "fmin": 1, "fmax": 15000, "db_min": 10, "db_max": 80, "cmap": "viridis", "frequency_scale": "linear"}
}
```

The function reads and writes only the URLs it is given and knows nothing about what is behind them; the caller decides where audio and images live and presigns accordingly. Every parameter is optional and defaults to what orcasite has always used, so images stay consistent with the existing archive. The response gives `image_size`, `sample_rate`, `width`, `height` and the `parameters` applied, plus the field names orcasite has stored since the first renderer.

The image is `n_fft/2` pixels high and one pixel wide per `hop_length` samples, as the previous renderer's STFT was. `db_min`/`db_max` are the dB window relative to an amplitude of 0.01, the convention the archive was drawn with; `DB_OFFSET` in `app.py` converts it to ffmpeg's full-scale dB and was fitted against a production image, whose luminance distribution the new render reproduces to within 0.01.

Until orcasite has switched, the previous shape (`audio_bucket`/`audio_key`, `image_bucket`/`image_key`, read and written with boto3) is also accepted; [`template.yaml`](template.yaml) keeps the S3 policy for it and both go once no caller uses them.

## Testing

[`tests/smoke.py`](tests/smoke.py) renders a synthetic AAC/MPEG-TS clip through the handler inside the built image, run as an unprivileged user with a root-owned empty `/tmp` and the CPU and memory of the deployed tier, which is how Lambda runs it. [CI](.github/workflows/ci.yml) runs it on every pull request; locally:

```bash
docker build -t spectrogram-renderer core
docker run --rm --user 1000:1000 --tmpfs /tmp:uid=0,gid=0,mode=1777 --cpus 0.58 --memory 1024m \
  --entrypoint python -v "$PWD/tests/smoke.py:/var/task/smoke.py" spectrogram-renderer smoke.py
```

That rehearses the application, not the sandbox: Lambda's Runtime Interface Emulator in the base image reproduces the invoke API, not the filesystem rules, hence the `--user` and `--tmpfs` flags.

## Deploying

Merging to `main` deploys: the [CI workflow](.github/workflows/ci.yml) runs the smoke test, then `sam build && sam deploy` under the `production` environment, assuming the `spectrogram-renderer-deploy` IAM role through GitHub's OIDC provider. That role can change only this stack (`audio-viz`, the name kept from when this lived in orcasite), its ECR repository and its function role.

To deploy from a machine instead, with an AWS profile for the Orcasound account and the [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html): `sam build && AWS_PROFILE=orcasound sam deploy`.

To invoke the deployed function on a real segment without writing anything ([`events/spectrogram_job.json`](events/spectrogram_job.json) reads from the public audio bucket and has `image_url` null):

```bash
aws lambda invoke --function-name "$(aws lambda list-functions --query "Functions[?contains(FunctionName,'AudioVizFunction')].FunctionName | [0]" --output text)" \
  --cli-binary-format raw-in-base64-out --payload "$(cat events/spectrogram_job.json)" /dev/stdout
```
