#!/bin/sh
# Dev-only helper for iterating on an addon in this repo (defaults to plugin.video.kayo).
# Usage: ./build-dev.sh [addon-id]
# Builds a fixed-name zip (dist/<addon-id>-dev.zip) whose INTERNAL version is
# bumped with an incrementing -dev<N> suffix every run, so "Install from zip file"
# always looks like a genuine upgrade and Kodi reloads the code (reuselanguageinvoker
# otherwise caches the old bytecode across same-version reinstalls).
# The committed addon.xml is never modified; the version is rewritten only in a staging copy.
# The dev counter is shared across addons so every build gets a higher suffix than any before it.
set -e
cd "$(dirname "$0")"
ID=${1:-plugin.video.kayo}
OUT=dist/${ID}-dev.zip
COUNTER=dist/.dev-counter

if [ ! -f "${ID}/addon.xml" ]; then
  echo "No addon.xml found for '${ID}'" >&2
  exit 1
fi

mkdir -p dist
BASE=$(sed -n "s/.*<addon id=\"${ID}\"[^>]*version=\"\([^\"]*\)\".*/\1/p" "${ID}/addon.xml")
BASE=${BASE%-dev*}
N=$(( $(cat "${COUNTER}" 2>/dev/null || echo 0) + 1 ))
echo "${N}" > "${COUNTER}"
DEV="${BASE}-dev${N}"

STAGE=$(mktemp -d)
trap 'rm -rf "${STAGE}"' EXIT
cp -R "${ID}" "${STAGE}/${ID}"
sed "s/version=\"${BASE}\"/version=\"${DEV}\"/" "${ID}/addon.xml" > "${STAGE}/${ID}/addon.xml"

rm -f "${OUT}"
(cd "${STAGE}" && zip -qr "${ID}.zip" "${ID}" -x '*__pycache__*' '*.pyc' '*.DS_Store' "${ID}/tests/*" "${ID}/README.md")
mv "${STAGE}/${ID}.zip" "${OUT}"
echo "${OUT} (version ${DEV})"
