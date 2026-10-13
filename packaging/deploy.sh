#!/usr/bin/env bash
# Installs the release tarball from dist/ on a Raspberry Pi over ssh and restarts the service, see BUILDING.md.
# The tarball has no .env and no log files, so the Pi keeps its own. Pass --env to also copy this repo's .env.
#
# Usage: ./packaging/deploy.sh <ssh host> [--env]
set -euo pipefail

cd "$(dirname "$0")/.."
host="${1:?usage: ./packaging/deploy.sh <ssh host> [--env]}"
copy_env="${2:-}"
version="${VERSION:-$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)}"
name="next-transit-display-${version}-linux-aarch64"
tarball="dist/${name}.tar.gz"
install_dir=/opt/next-transit-display

if [ -n "${copy_env}" ] && [ "${copy_env}" != "--env" ]; then
  echo "usage: ./packaging/deploy.sh <ssh host> [--env]" >&2
  exit 1
fi
if [ ! -f "${tarball}" ]; then
  echo "No ${tarball}, build it first with ./packaging/build.sh" >&2
  exit 1
fi
if [ "${copy_env}" = "--env" ] && [ ! -f .env ]; then
  echo "No .env in $(pwd) to copy" >&2
  exit 1
fi

# A folder on the Pi that only the ssh user can read, made fresh for this deploy. Other users can't read the API keys
# in .env on the way, and nothing left by an earlier, interrupted deploy gets installed
staging="$(ssh "${host}" mktemp -d)"
trap 'ssh "${host}" "rm -rf ${staging}" || true' EXIT

scp "${tarball}" "${host}:${staging}/release.tar.gz"
if [ "${copy_env}" = "--env" ]; then
  scp .env "${host}:${staging}/.env"
fi

# Stopped before unpacking, so the program never runs with a mix of old and new files. A program that exits at startup,
# such as on a bad .env, shows as activating while systemd waits to restart it, so the last check fails the deploy
ssh "${host}" "set -e
  sudo mkdir -p ${install_dir}
  sudo systemctl stop next-transit-display.service || true
  sudo tar -xzf ${staging}/release.tar.gz -C ${install_dir} --strip-components=1
  if [ '${copy_env}' = '--env' ]; then
    sudo install -m 600 ${staging}/.env ${install_dir}/.env
  fi
  if [ ! -f ${install_dir}/.env ]; then
    echo 'No ${install_dir}/.env on the Pi, copy .env.example to it and fill it in' >&2
    exit 1
  fi
  sudo install -m 644 ${install_dir}/next-transit-display.service /etc/systemd/system/next-transit-display.service
  sudo systemctl daemon-reload
  sudo systemctl enable next-transit-display.service
  sudo systemctl restart next-transit-display.service
  sleep 3
  systemctl status next-transit-display.service --no-pager | head -5
  if ! systemctl is-active --quiet next-transit-display.service; then
    echo 'next-transit-display.service is not running, see journalctl -u next-transit-display.service' >&2
    exit 1
  fi"
