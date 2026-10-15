#!/bin/sh
# Build the GitHub Pages site under dist/: the Kodi repository feed in repository.nerv/
# (each addon zip in <id>/<id>-<version>.zip, addons.xml, addons.xml.md5), and at the root
# only the repository zip plus an index.html Kodi can browse as a file source
set -e
cd "$(dirname "$0")"
ADDONS="plugin.video.kayo repository.nerv"
FEED=dist/repository.nerv
rm -rf dist
mkdir -p "${FEED}"
printf '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n' > "${FEED}/addons.xml"
for ID in ${ADDONS}; do
  VERSION=$(sed -n "s/.*<addon id=\"${ID}\"[^>]*version=\"\([^\"]*\)\".*/\1/p" "${ID}/addon.xml")
  mkdir -p "${FEED}/${ID}"
  zip -qr "${FEED}/${ID}/${ID}-${VERSION}.zip" "${ID}" -x '*__pycache__*' '*.pyc' '*.DS_Store' "${ID}/tests/*" "${ID}/README.md"
  cp "${ID}/addon.xml" "${ID}/icon.png" "${FEED}/${ID}/"
  if [ -f "${ID}/fanart.jpg" ]; then cp "${ID}/fanart.jpg" "${FEED}/${ID}/"; fi
  sed '/^<?xml/d' "${ID}/addon.xml" >> "${FEED}/addons.xml"
  echo "${FEED}/${ID}/${ID}-${VERSION}.zip"
done
echo '</addons>' >> "${FEED}/addons.xml"
if command -v md5sum >/dev/null; then
  md5sum "${FEED}/addons.xml" | cut -d' ' -f1 > "${FEED}/addons.xml.md5"
else
  md5 -q "${FEED}/addons.xml" > "${FEED}/addons.xml.md5"
fi
cp "${FEED}"/repository.nerv/*.zip dist/
REPO_ZIP=$(cd dist && ls repository.nerv-*.zip)
cat > dist/index.html <<HTML
<!DOCTYPE html>
<html><body>
<a href="${REPO_ZIP}">${REPO_ZIP}</a>
</body></html>
HTML
