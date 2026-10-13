#!/usr/bin/env bash
# Builds the release tarball for 64-bit Raspberry Pi OS into dist/, see BUILDING.md.
# Needs Docker with BuildKit. On an Apple silicon Mac the arm64 image runs natively, elsewhere through emulation.
set -euo pipefail

cd "$(dirname "$0")/.."
version="${VERSION:-$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)}"
name="next-transit-display-${version}-linux-aarch64"

rm -f "dist/${name}.tar.gz" "dist/${name}.tar.gz.sha256"
docker build --platform linux/arm64 --file packaging/Dockerfile --target artifact --build-arg "RELEASE_NAME=${name}" \
  --output "type=local,dest=dist" .
echo "Built dist/${name}.tar.gz"
