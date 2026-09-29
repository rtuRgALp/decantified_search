#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

echo "Setting up Decantified Search..."
echo "Project: ${PROJECT_ROOT}"

if command -v xcode-select >/dev/null 2>&1; then
  if xcode-select -p >/dev/null 2>&1; then
    echo "Apple Command Line Tools: installed"
  else
    echo "Apple Command Line Tools: missing"
    echo "Run this command, then follow the macOS installer prompt:"
    echo "  xcode-select --install"
  fi
else
  echo "xcode-select was not found. Install Apple's Command Line Tools from macOS."
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 was not found. Install Apple Command Line Tools or Python 3, then rerun this script."
  exit 1
fi

if ! "${PYTHON_BIN}" --version >/dev/null 2>&1; then
  echo "python3 is present but cannot run yet. Finish the Apple Command Line Tools installation, then rerun this script."
  exit 1
fi

echo "Python: ${PYTHON_BIN}"

if [ ! -d "${VENV_DIR}" ]; then
  echo "Creating virtual environment..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  echo "Virtual environment: already exists"
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip

if [ -s "${PROJECT_ROOT}/requirements.txt" ] && grep -Ev '^\s*(#|$)' "${PROJECT_ROOT}/requirements.txt" >/dev/null; then
  python -m pip install -r "${PROJECT_ROOT}/requirements.txt"
else
  echo "No third-party Python dependencies to install."
fi

echo
echo "Setup complete."
echo "Run the scraper with:"
echo "  ./.venv/bin/python scrape_tobacco_decants.py"
