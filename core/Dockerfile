# ffmpeg does all the work; the handler is standard library plus the boto3
# the base image ships, so there is nothing to pip install and no cache to
# warm. A static build keeps the image at the base plus two binaries.
#
# Both images are pinned by tag and digest so that a rebuild gets the same
# bytes, and Dependabot (.github/dependabot.yml) proposes new versions of each.
FROM mwader/static-ffmpeg:9.1@sha256:dd09509d8c2152bfa601c8c20e3dd166bde906d37951b9f7e8bbd922267f5ac9 AS ffmpeg

FROM public.ecr.aws/lambda/python:3.15@sha256:ff118eaa5fb0e4a322ae28c5b8a7337f5396eaca5f34d613b904b444f8a32dc0

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY app.py ./

CMD ["app.lambda_handler"]
