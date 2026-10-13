# syntax=docker/dockerfile:1
# Builds next-transit-display as a standalone aarch64 binary for 64-bit Raspberry Pi OS Bookworm. Run it through
# packaging/build.sh, see BUILDING.md.
#
# build.sh selects the linux/arm64 platform. The image matches the Pi's own userland: Debian Bookworm's python3 is
# 3.11.2, the version pyproject.toml pins, and building against Bookworm's glibc 2.36 means the binary runs on the Pi
# without a newer one.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS build

# the LED matrix library at the commit the Pi's own install was built from, so the binary drives the panel the same way
ARG RGB_MATRIX_COMMIT=59a5e0574ec1528298ad25111a9bbdf2a2fa7a67
ARG UV_VERSION=0.13.0
ARG NUITKA_VERSION=4.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-dev python3-venv build-essential cython3 git ca-certificates patchelf ccache \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir "uv==${UV_VERSION}"
ENV PATH=/opt/venv/bin:$PATH

# rpi-rgb-led-matrix is not on PyPI, so its Python bindings are built from source into the venv
RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix /opt/rpi-rgb-led-matrix \
    && git -C /opt/rpi-rgb-led-matrix checkout "${RGB_MATRIX_COMMIT}" \
    && make -C /opt/rpi-rgb-led-matrix build-python PYTHON=/opt/venv/bin/python \
    && make -C /opt/rpi-rgb-led-matrix install-python PYTHON=/opt/venv/bin/python

WORKDIR /src
COPY pyproject.toml uv.lock ./
# exactly the versions uv.lock pins, so every build bundles the same libraries
RUN uv export --frozen --no-dev --no-emit-project --no-hashes --output-file /tmp/requirements.txt \
    && uv pip install --python /opt/venv/bin/python --no-cache -r /tmp/requirements.txt "nuitka==${NUITKA_VERSION}"

COPY main.py ./
COPY models ./models
COPY modules ./modules
COPY services ./services

# RGBMatrixEmulator is the development stand-in for the real library and never ships. _json is the C accelerator
# for the json module, which Nuitka otherwise leaves out and falls back to pure Python. The cache mount keeps Nuitka's
# and ccache's compiled objects between builds, which makes a rebuild much faster
RUN --mount=type=cache,target=/root/.cache \
    python -m nuitka \
        --standalone \
        --assume-yes-for-downloads \
        --nofollow-import-to=RGBMatrixEmulator \
        --include-module=_json \
        --output-dir=/build \
        --output-filename=next-transit-display \
        main.py

# The release tarball is made here rather than on the build machine, so it comes out the same from any of them: every
# file owned by root, which runs it on the Pi, and none of the extended attributes macOS adds, which the Pi's tar
# warns about. build.sh passes RELEASE_NAME
FROM build AS package
ARG RELEASE_NAME
WORKDIR /package/${RELEASE_NAME}
RUN cp -a /build/main.dist/. .
# everything the program reads at runtime from its working directory, plus what an install needs
COPY fonts ./fonts
COPY .env.example ENVIRONMENT.md LICENSE \
    packaging/next-transit-display.service packaging/next-transit-display-python.service ./
RUN mkdir /out \
    && tar -C /package --owner=0 --group=0 --numeric-owner -czf "/out/${RELEASE_NAME}.tar.gz" "${RELEASE_NAME}" \
    && cd /out && sha256sum "${RELEASE_NAME}.tar.gz" > "${RELEASE_NAME}.tar.gz.sha256"

# only the tarball and its checksum, so build.sh can export them with docker build --output
FROM scratch AS artifact
COPY --from=package /out/ /
