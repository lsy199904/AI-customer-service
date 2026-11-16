#!/bin/sh
# Administrator credentials are used only by a temporary preparation job.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
exec python3 scripts/kubernetes.py cloud "$@"
