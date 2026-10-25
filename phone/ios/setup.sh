#!/usr/bin/env bash
# Generate GlassesRelay.xcodeproj. Needs XcodeGen (brew install xcodegen).
set -euo pipefail
cd "$(dirname "$0")"
[ -f Config.xcconfig ] || { cp Config.example.xcconfig Config.xcconfig; echo "created Config.xcconfig: set DEVELOPMENT_TEAM before installing on a phone"; }
xcodegen generate
echo "open GlassesRelay.xcodeproj"
