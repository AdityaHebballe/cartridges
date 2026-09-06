#!/usr/bin/env bash
set -e
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure prefix has latest build
if [ ! -f "$REPO_DIR/_build/prefix/bin/cartridges" ]; then
    meson compile -C "$REPO_DIR/_build"
    meson install -C "$REPO_DIR/_build"
fi

export XDG_DATA_DIRS="$REPO_DIR/_build/prefix/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export PYTHONPATH="$REPO_DIR/_build/prefix/lib/python3.14/site-packages:${PYTHONPATH}"
exec "$REPO_DIR/_build/prefix/bin/cartridges" "$@"
