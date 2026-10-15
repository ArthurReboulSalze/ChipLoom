#!/bin/sh
set -eu
cd -- "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ]; then
    printf '%s\n' 'Cree un environnement avec python3 -m venv .venv, puis .venv/bin/python -m pip install -e ".[desktop]".' >&2
    exit 1
fi
exec .venv/bin/python -m tracker4agents gui "$@"
