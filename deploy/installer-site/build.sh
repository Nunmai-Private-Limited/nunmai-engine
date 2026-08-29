#!/bin/bash
# Copy the canonical installers from the repo into the static site.
set -e
cd "$(dirname "$0")"
cp ../../scripts/install.sh  public/install.sh
cp ../../scripts/install.ps1 public/install.ps1
echo "installer-site: copied install.sh ($(wc -l < public/install.sh) lines), install.ps1 ($(wc -l < public/install.ps1) lines)"
