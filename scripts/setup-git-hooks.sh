#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v pre-commit >/dev/null 2>&1; then
	if command -v uv >/dev/null 2>&1; then
		uv tool install pre-commit
	elif command -v pipx >/dev/null 2>&1; then
		pipx install pre-commit
	else
		pip install --user pre-commit
	fi
fi

pre-commit install --install-hooks --overwrite
