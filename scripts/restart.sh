#!/usr/bin/env bash
set -euo pipefail

sudo systemctl restart techsterownik-auto-lato
sudo systemctl status techsterownik-auto-lato --no-pager
