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

scp "${tarball}" "${host}:/tmp/${name}.tar.gz"
if [ "${copy_env}" = "--env" ]; then
  scp .env "${host}:/tmp/next-transit-display.env"
fi

# stopped before unpacking, since the running binary can't be overwritten in place
ssh "${host}" "set -e
  sudo mkdir -p ${install_dir}
  sudo systemctl stop next-transit-display.service || true
  sudo tar -xzf /tmp/${name}.tar.gz -C ${install_dir} --strip-components=1
  rm /tmp/${name}.tar.gz
  if [ -f /tmp/next-transit-display.env ]; then
    sudo install -m 600 /tmp/next-transit-display.env ${install_dir}/.env
    rm /tmp/next-transit-display.env
  fi
  if [ ! -f ${install_dir}/.env ]; then
    echo 'No ${install_dir}/.env on the Pi, copy .env.example to it and fill it in' >&2
    exit 1
  fi
  sudo install -m 644 ${install_dir}/next-transit-display.service /etc/systemd/system/next-transit-display.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now next-transit-display.service
  sudo systemctl restart next-transit-display.service
  systemctl status next-transit-display.service --no-pager | head -5"
