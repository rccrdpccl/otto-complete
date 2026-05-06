#!/usr/bin/env bash
set -euo pipefail

git config --global user.name "otto-complete"
git config --global user.email "otto-complete@noreply.github.com"

exec python -m otto_complete
