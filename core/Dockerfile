FROM public.ecr.aws/lambda/python:3.14

# ffmpeg does all the work; the handler is standard library plus the boto3
# the base image ships, so there is nothing to pip install and no cache to
# warm. A static build keeps the image at the base plus one binary.
ARG FFMPEG_VERSION=ffmpeg-7.0.2-amd64-static
RUN dnf install -y tar xz \
  && curl -sO https://johnvansickle.com/ffmpeg/releases/${FFMPEG_VERSION}.tar.xz \
  && tar -xf ${FFMPEG_VERSION}.tar.xz \
  && mv ${FFMPEG_VERSION}/ffmpeg ${FFMPEG_VERSION}/ffprobe /usr/local/bin/ \
  && rm -rf ${FFMPEG_VERSION} ${FFMPEG_VERSION}.tar.xz \
  && dnf clean all

COPY app.py ./

CMD ["app.lambda_handler"]
