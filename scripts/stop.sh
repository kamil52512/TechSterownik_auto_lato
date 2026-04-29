#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop techsterownik-auto-lato
sudo systemctl status techsterownik-auto-lato --no-pager || true
