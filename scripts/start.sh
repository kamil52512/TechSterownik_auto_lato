#!/usr/bin/env bash
set -euo pipefail

sudo systemctl start techsterownik-auto-lato
sudo systemctl status techsterownik-auto-lato --no-pager
