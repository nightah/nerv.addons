# Tennis TV player headshots and flags

The Match Info overlay shows a headshot and a country flag per player. Both are vendored, keyed by the ATP player sid and the three-letter country code the API returns.

Headshots come from `atptour.com`, which gates on a Cloudflare TLS-fingerprint challenge that no plain HTTP client (curl, Kodi's image loader) can pass, so only a real browser can fetch them. The roster to vendor is every entrant in this and last season's tournament draws. Flags come from the Tennis TV site's own SVGs and are rasterised to PNG, since Kodi has no SVG support.

## Re-vendor headshots

1. Print the harvester (roster sids baked in):

   ```sh
   python3 tools/tennistv-headshots/vendor.py --harvester
   ```

2. Open any headshot URL in Chrome so the page is on the atptour.com origin with Cloudflare cleared, for example `https://www.atptour.com/-/media/alias/player-headshot/S0AG`. Open the DevTools console and paste the harvester. It fetches every headshot, then adds a COPY button. The full set is tens of MB, too large for one clipboard write, so click the button once per batch:

   ```sh
   pbpaste > batch1.json   # after the first click
   pbpaste > batch2.json   # after the second click, and so on
   ```

3. Install from the batches:

   ```sh
   cat batch*.json | python3 tools/tennistv-headshots/vendor.py --install
   ```

   Each headshot is resized to 160px, compressed with pngquant and written to `resources/media/players/<sid>.png`. Files not in the bundle (such as retired legends) are kept.

## Re-vendor flags

```sh
python3 tools/tennistv-headshots/vendor.py --flags
```

Fetches the site's flag SVG for each roster nationality and rasterises it to `resources/media/flags/<code>.png`. Countries with no flag on the site (such as neutral RUS and BLR) are skipped.

## Requirements

- `sips` (macOS) and `pngquant` (`brew install pngquant`) for headshots
- `rsvg-convert` (`brew install librsvg`) for flags
