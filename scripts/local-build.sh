#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-"${ROOT_DIR}/_build_local"}"
PREFIX="${PREFIX:-/usr}"
PROFILE="${PROFILE:-release}"
TIFF_COMPRESSION="${TIFF_COMPRESSION:-jpeg}"
COMMAND="${1:-install}"

cd "${ROOT_DIR}"

app_id() {
  if [[ "${PROFILE}" = development ]]; then
    printf 'page.kramo.Cartridges.Devel'
  else
    printf 'page.kramo.Cartridges'
  fi
}

setup() {
  if [[ -f "${BUILD_DIR}/meson-info/meson-info.json" ]]; then
    meson setup --reconfigure "${BUILD_DIR}" "${ROOT_DIR}" \
      --prefix "${PREFIX}" \
      -Dprofile="${PROFILE}" \
      -Dtiff_compression="${TIFF_COMPRESSION}"
  else
    meson setup "${BUILD_DIR}" "${ROOT_DIR}" \
      --prefix "${PREFIX}" \
      -Dprofile="${PROFILE}" \
      -Dtiff_compression="${TIFF_COMPRESSION}"
  fi
}

install_app() {
  setup
  meson compile -C "${BUILD_DIR}"

  if [[ "${PREFIX}" = /usr* && "${EUID}" -ne 0 ]]; then
    sudo meson install -C "${BUILD_DIR}"
  else
    meson install -C "${BUILD_DIR}"
  fi
}

run_app() {
  if [[ "${CARTRIDGES_SKIP_INSTALL:-0}" != 1 ]]; then
    install_app
  fi

  if [[ "${CARTRIDGES_KEEP_RUNNING:-0}" != 1 ]] && command -v gapplication >/dev/null; then
    gapplication quit "$(app_id)" >/dev/null 2>&1 || true
  fi

  if [[ -n "${CARTRIDGES_PROFILE_STARTUP:-}" ]]; then
    export CARTRIDGES_NON_UNIQUE="${CARTRIDGES_NON_UNIQUE:-1}"
  fi

  if [[ "${PREFIX}" != /usr* ]]; then
    python_path="$(
      python -c 'import sys, sysconfig; print(sysconfig.get_path("purelib", vars={"base": sys.argv[1], "platbase": sys.argv[1]}))' "${PREFIX}"
    )"
    export PYTHONPATH="${python_path}:${PYTHONPATH:-}"
    export GSETTINGS_SCHEMA_DIR="${PREFIX}/share/glib-2.0/schemas"
    export XDG_DATA_DIRS="${PREFIX}/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
  fi
  exec "${PREFIX}/bin/cartridges" "$@"
}

case "${COMMAND}" in
  setup)
    setup
    ;;
  install)
    install_app
    ;;
  run)
    shift
    run_app "$@"
    ;;
  test)
    setup
    python -c 'import ast, pathlib; [ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in pathlib.Path("cartridges").rglob("*.py")]'
    python -m unittest discover -s tests
    meson test -C "${BUILD_DIR}" --print-errorlogs
    ;;
  clean)
    rm -rf "${BUILD_DIR}"
    ;;
  *)
    printf 'Usage: %s [setup|install|run|test|clean]\n' "$0" >&2
    exit 2
    ;;
esac
