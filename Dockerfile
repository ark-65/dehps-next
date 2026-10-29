ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
WORKDIR /app
LABEL io.dehps-next.owner="dehps-next"
COPY requirements.lock /tmp/requirements.lock
ARG PYPI_INDEX_URL=https://pypi.org/simple
RUN grep '^torch==' /tmp/requirements.lock > /tmp/torch.lock \
    && grep -v '^torch==' /tmp/requirements.lock > /tmp/base.lock \
    && pip install --no-cache-dir --no-deps --timeout=60 --index-url https://download.pytorch.org/whl/cpu -r /tmp/torch.lock \
    && pip install --no-cache-dir --timeout=60 --index-url ${PYPI_INDEX_URL} -r /tmp/base.lock
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir --no-deps --no-build-isolation .
ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
USER 1000:1000
ENTRYPOINT ["dehps-next"]
