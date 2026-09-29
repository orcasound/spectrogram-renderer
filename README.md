# spectrogram-renderer

A Lambda function that renders one spectrogram PNG from one hydrophone audio segment. [Orcasite](https://github.com/orcasound/orcasite) invokes it by name from [`Orcasite.Radio.AwsClient`](https://github.com/orcasound/orcasite/blob/main/server/lib/orcasite/radio/aws_client.ex), once per `AudioImage`, passing the S3 location of the segment and where to put the image. It has no other entry point.

- [`core/app.py`](core/app.py): the handler. Downloads the segment, decodes it with ffmpeg, renders with [`core/spectrogram_generator.py`](core/spectrogram_generator.py), uploads the PNG.
- [`core/Dockerfile`](core/Dockerfile): the image, built on the AWS Lambda Python base with a static ffmpeg.
- [`template.yaml`](template.yaml): the function's memory, timeout and IAM policy, as a SAM template. Stack name (`audio-viz`, kept from when this lived in orcasite) and region are in [`samconfig.toml`](samconfig.toml).

## Cold starts

A new Lambda container starts with an empty `/tmp`, where numba, librosa and matplotlib keep their caches, so the first render in a container recompiles librosa's numba functions and rebuilds the font list. The Dockerfile runs [`warm.py`](core/warm.py) once at build time and keeps the caches it leaves in the image; [`app.py`](core/app.py) copies them into `/tmp` before importing those libraries. If you add a library that caches on first use, give it a directory under `/tmp` in the Dockerfile and add it to the same `mv`.

To check a deployed function, find `platform.report` records in its CloudWatch log (the template sets `LogFormat: JSON`). Cold invocations carry `initDurationMs`; their `durationMs + initDurationMs` should be within a couple of seconds of a warm invocation's `durationMs`. Lambda's `Duration` metric excludes init time, so it alone understates a cold start.

## Testing

[`tests/smoke.py`](tests/smoke.py) renders a synthetic MPEG-TS clip inside the built image, run as an unprivileged user with a root-owned empty `/tmp` and the CPU and memory of the deployed tier, which is how Lambda runs it. It fails if the first render is slow enough to suggest the caches were not restored. [CI](.github/workflows/ci.yml) runs it on every pull request; locally:

```bash
docker build -t spectrogram-renderer core
docker run --rm --user 1000:1000 --tmpfs /tmp:uid=0,gid=0,mode=1777 --cpus 0.58 --memory 1024m \
  --entrypoint python -v "$PWD/tests/smoke.py:/var/task/smoke.py" spectrogram-renderer smoke.py
```

That rehearses the application, not the sandbox: Lambda's Runtime Interface Emulator in the base image reproduces the invoke API, not the filesystem rules. Anything that touches `/tmp`'s own metadata or relies on image contents under `/tmp` will pass locally on a plain tmpfs and fail deployed, hence the `--user` and `--tmpfs` flags above.

## Deploying

Merging to `main` deploys: the [CI workflow](.github/workflows/ci.yml) runs the smoke test, then `sam build && sam deploy` under the `production` environment, assuming the `spectrogram-renderer-deploy` IAM role through GitHub's OIDC provider. That role can change only this stack, its ECR repository and its function role.

To deploy from a machine instead, with an AWS profile for the Orcasound account and the [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html):

```bash
sam build
AWS_PROFILE=orcasound sam deploy
```

To invoke the deployed function on a real segment without writing anything (`image_key` null skips the upload):

```bash
aws lambda invoke --function-name "$(aws lambda list-functions --query "Functions[?contains(FunctionName,'AudioVizFunction')].FunctionName | [0]" --output text)" \
  --cli-binary-format raw-in-base64-out --payload "$(cat events/spectrogram_job.json)" /dev/stdout
```
