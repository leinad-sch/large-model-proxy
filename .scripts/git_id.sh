#!/usr/bin/env sh
set -eu

# 1. Try a tag first
TAG=$(git describe --tags --exact-match 2>/dev/null || true)

if [ -n "$TAG" ]; then
    echo "$TAG"
    exit 0
fi

# 2. No tag → branch + commits + hash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" = "HEAD" ]; then
    BRANCH="detached"
fi
# Replace any "/" in branch name with "_" to prevent issues
BRANCH=$(echo "$BRANCH" | sed 's/\//_/g')
COUNT=$(git rev-list --count HEAD)
HASH=$(git rev-parse --short HEAD)

echo "${BRANCH}-${COUNT}-${HASH}"
