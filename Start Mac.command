#!/bin/zsh
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -r requirements.txt || exit 1
.venv/bin/python run.py
