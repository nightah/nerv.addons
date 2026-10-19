# Tennis TV player headshots

The Players menu shows a headshot per player, vendored into `plugin.video.tennistv/resources/media/players/<sid>.png` and keyed by the ATP player sid the catalogue already uses.

The source images live on `atptour.com` behind a Cloudflare bot challenge that no plain HTTP client (curl, Kodi's image loader) can pass, and the challenge gates on the TLS fingerprint, not on headers or auth, so it cannot be emulated. A real browser is the only client that gets through, which is why the images are vendored rather than fetched at runtime.

## Re-vendor

Run when the featured-players list changes (new players appear, or you want fresher photos).

1. Print the harvester, with the current sids baked in:

   ```sh
   python3 tools/tennistv-headshots/vendor.py --harvester
   ```

2. Open any headshot URL in Chrome so the page is on the atptour.com origin with Cloudflare cleared, for example `https://www.atptour.com/-/media/alias/player-headshot/S0AG`. Open the DevTools console, paste the harvester, and click the COPY BUNDLE button it adds. It fetches every headshot and copies a JSON bundle (`{sid: base64 png}`) to the clipboard.

3. Install from the clipboard:

   ```sh
   pbpaste | python3 tools/tennistv-headshots/vendor.py --install
   ```

   This resizes each headshot to 160px, compresses it with pngquant, writes `<sid>.png`, and prunes players no longer listed.

## Requirements

- `sips` (macOS, built in) for resizing
- `pngquant` (`brew install pngquant`) for compression
