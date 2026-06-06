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

python_paths() {
  python - <<'PY'
import site
import sysconfig
from pathlib import Path

paths = set()

user_site = site.getusersitepackages()
if isinstance(user_site, str):
    paths.add(user_site)
else:
    paths.update(user_site)

paths.add(sysconfig.get_path("purelib", vars={"base": "/usr", "platbase": "/usr"}))
paths.add(sysconfig.get_path("platlib", vars={"base": "/usr", "platbase": "/usr"}))

for path in sorted(Path(path) for path in paths if path):
    print(path)
PY
}

cleanup_stale_python_package() {
  if [[ "${CARTRIDGES_SKIP_STALE_CLEANUP:-0}" = 1 ]]; then
    return
  fi

  local paths=()
  while IFS= read -r package_root; do
    [[ -n "${package_root}" ]] || continue
    if [[ "${PREFIX}" != /usr* && "${package_root}" = /usr/* ]]; then
      continue
    fi
    paths+=("${package_root}/cartridges")
    paths+=("${package_root}"/cartridges-*.dist-info)
    paths+=("${package_root}"/cartridges-*.egg-info)
  done < <(python_paths)

  if (( ${#paths[@]} == 0 )); then
    return
  fi

  if [[ "${PREFIX}" = /usr* && "${EUID}" -ne 0 ]]; then
    sudo rm -rf -- "${paths[@]}"
  else
    rm -rf -- "${paths[@]}"
  fi
}

quit_running_app() {
  if [[ "${CARTRIDGES_KEEP_RUNNING:-0}" = 1 ]]; then
    return
  fi

  if command -v gapplication >/dev/null; then
    gapplication quit "$(app_id)" >/dev/null 2>&1 || true
  fi

  if ! command -v busctl >/dev/null; then
    return
  fi

  local pid
  pid="$(
    busctl --user list --no-legend 2>/dev/null \
      | awk -v app="$(app_id)" '$1 == app { print $2; exit }'
  )"

  if [[ -n "${pid}" && "${pid}" != "-" && "${pid}" != "$$" ]]; then
    kill "${pid}" >/dev/null 2>&1 || true
  fi
}

install_app() {
  if [[ "${CARTRIDGES_CLEAN_INSTALL:-1}" = 1 ]]; then
    rm -rf "${BUILD_DIR}"
  fi

  quit_running_app

  setup
  meson compile -C "${BUILD_DIR}"
  cleanup_stale_python_package

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

  quit_running_app

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
