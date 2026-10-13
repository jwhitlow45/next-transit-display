Link back to [README.md](README.md).

---

# Building and releasing the standalone binary

Each GitHub release carries a standalone build for 64-bit Raspberry Pi OS Bookworm on a Pi 3 or newer (`aarch64`). It is the same program as `sudo python3 main.py`, compiled with [Nuitka](https://nuitka.net/) and packaged with everything it needs: the Python runtime, every dependency, and the LED matrix library. Nothing has to be installed on the Pi first, and the setup script is not needed.

The binary does not change how the display looks or how fast it refreshes. The LED matrix library already runs as compiled C++ either way, and the program's own Python work uses about 1% of a core. What it changes is the install: one download, no Python packages to keep in step on the Pi.

## What the build pins

The build runs in Docker, from `packaging/Dockerfile`, so it comes out the same on any machine:

- Debian Bookworm, pinned by image digest. Its `python3` is 3.11.2, the version `pyproject.toml` requires, and its glibc 2.36 matches Raspberry Pi OS Bookworm.
- [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) at a fixed commit, `RGB_MATRIX_COMMIT`.
- uv and Nuitka at fixed versions, `UV_VERSION` and `NUITKA_VERSION`.
- Every Python dependency at the version `uv.lock` pins.

To move any of these forward, change the value in `packaging/Dockerfile` (or update `uv.lock` with `uv lock`), then rebuild and test on the Pi before releasing.

## Building

Requirements: Docker with BuildKit, such as Docker Desktop. The image is `linux/arm64`. On an Apple silicon Mac it builds natively. On an `x86_64` machine Docker builds it through emulation, which works but is much slower.

From the root of the repo:
```
./packaging/build.sh
```
This writes two files to `dist/`:
- `next-transit-display-<version>-linux-aarch64.tar.gz`, the release
- `next-transit-display-<version>-linux-aarch64.tar.gz.sha256`, its checksum

The version comes from `pyproject.toml`. Set `VERSION` to override it, for example `VERSION=0.1.0-test ./packaging/build.sh`. The first build compiles everything and takes a while. Later builds reuse Docker's cached layers and Nuitka's compile cache.

The tarball holds one folder with:
- `next-transit-display`, the program, and the libraries Nuitka bundled beside it
- `fonts/`, which the program loads at runtime
- `.env.example`, `ENVIRONMENT.md` and `LICENSE`
- `next-transit-display.service`, a systemd unit
- `next-transit-display-python.service`, a systemd unit for development, see [Developing on a Pi that runs the release](#developing-on-a-pi-that-runs-the-release)

## Installing on the Pi

The program needs root for the GPIO pins, and reads `.env` and `fonts/` from its working directory. The unit file assumes `/opt/next-transit-display`.

1. Copy the release to the Pi and unpack it:
   ```
   scp next-transit-display-<version>-linux-aarch64.tar.gz <user>@<host>:/tmp/
   ssh <user>@<host>
   sudo mkdir -p /opt/next-transit-display
   sudo tar -xzf /tmp/next-transit-display-<version>-linux-aarch64.tar.gz -C /opt/next-transit-display --strip-components=1
   ```
2. Create the configuration. Copy `.env.example` to `.env` and fill it in (see [ENVIRONMENT.md](ENVIRONMENT.md)), or copy over an existing `.env`:
   ```
   sudo cp /opt/next-transit-display/.env.example /opt/next-transit-display/.env
   sudo nano /opt/next-transit-display/.env
   ```
3. Install and start the service:
   ```
   sudo cp /opt/next-transit-display/next-transit-display.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now next-transit-display.service
   ```
4. Check it started:
   ```
   systemctl status next-transit-display.service
   journalctl -u next-transit-display.service -f
   ```

If the Pi already runs the Python version under a service of the same name, step 3 replaces that unit. Copy the old `.env` to `/opt/next-transit-display/.env` first. The log files start fresh in `/opt/next-transit-display`, and the old ones stay where they were.

To upgrade, unpack a newer release over the same folder and restart the service. The tarball has no `.env`, so the configuration and the log files stay as they are.

The LED matrix library's own advice still applies to the Pi: it runs best with the onboard sound off and `isolcpus=3` on the kernel command line. See the library's [README](https://github.com/hzeller/rpi-rgb-led-matrix#troubleshooting).

## Deploying to a Pi over ssh

`packaging/deploy.sh` installs the tarball from `dist/` on a Pi you can reach with ssh, then restarts the service. From the root of the repo:
```
./packaging/build.sh && ./packaging/deploy.sh <ssh host>
```
It unpacks into `/opt/next-transit-display` and installs `next-transit-display.service`. The Pi keeps its own `.env` and log files. Add `--env` to copy this repo's `.env` over the Pi's first:
```
./packaging/deploy.sh <ssh host> --env
```
The first deploy to a Pi needs a `.env` there, so use `--env` or create it as in step 2 above.

## Developing on a Pi that runs the release

A build and deploy takes about a minute. While changing code, it's quicker to sync the Python source to the Pi and run that, and build only when done. `next-transit-display-python.service` runs the source from `/home/muni/next-transit-display`. Edit its two paths if the source lives somewhere else. Starting either service stops the other, so the two never drive the panel at once. The Python service has no `[Install]` section, so it can't be enabled, and the Pi always boots into the release.

The source needs the Python setup from the README's install script on the Pi. It reads its own `.env` from its own folder, separate from the release's.

1. Install the unit once, on the Pi:
   ```
   sudo cp /opt/next-transit-display/next-transit-display-python.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
2. After each change, sync the source and restart it, from the root of the repo. The excludes keep `--delete` away from the Pi's `.env` and log files:
   ```
   rsync -aPh --delete --filter=':- .gitignore' --exclude=.git/ --exclude=.jj/ --exclude=.env --exclude='*.log*' --exclude=.venv/ --exclude=__pycache__/ --exclude=.ruff_cache/ --exclude=.mypy_cache/ --exclude=.claude/ . <user>@<host>:/home/muni/next-transit-display
   scp .env <user>@<host>:/home/muni/next-transit-display/.env
   ssh <user>@<host> 'sudo systemctl restart next-transit-display-python.service'
   ```
3. When done, build and deploy the release. Its service stops the Python one:
   ```
   ./packaging/build.sh && ./packaging/deploy.sh <ssh host>
   ```

## Releasing

1. Set `version` in `pyproject.toml` to the new version and commit it.
2. Build with `./packaging/build.sh`, and test the tarball on the Pi.
3. Push the commit, then create the GitHub release with the tarball and its checksum. `--target` tags the pushed commit:
   ```
   gh release create v<version> \
     dist/next-transit-display-<version>-linux-aarch64.tar.gz \
     dist/next-transit-display-<version>-linux-aarch64.tar.gz.sha256 \
     --target main --title "v<version>" --notes "<what changed>"
   ```

---

Link back to [README.md](README.md).
