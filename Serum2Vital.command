#!/bin/zsh

# Finder-friendly launcher for the development checkout.
set -u

project_dir="${0:A:h}"
cd -- "$project_dir" || exit 1

python_bin="${SERUM2VITAL_PYTHON:-}"
if [[ -z "$python_bin" && -x "$project_dir/.venv/bin/python3" ]]; then
  python_bin="$project_dir/.venv/bin/python3"
fi
if [[ -z "$python_bin" ]]; then
  python_bin="${commands[python3]:-}"
fi

if [[ -z "$python_bin" ]] || ! "$python_bin" -c 'import PySide6' >/dev/null 2>&1; then
  /usr/bin/osascript -e 'display alert "Serum2Vitalを起動できません" message "Python用GUIが未インストールです。ターミナルで python3 -m pip install -e \".[gui,serum2]\" を実行してください。" as critical'
  exit 1
fi

exec "$python_bin" -m serum2vital.gui
