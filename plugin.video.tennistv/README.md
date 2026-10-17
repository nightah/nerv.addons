# plugin.video.tennistv

Watch ATP tour replays, highlights and features from a [Tennis TV](https://www.tennistv.com) subscription in
Kodi. Built on the [SlyGuy](https://slyguy.uk) framework, mirroring the structure of this repo's
`plugin.video.kayo` addon.

> Subscription required. Requires `script.module.slyguy` (installed automatically from the NERV Repository) and
> Kodi 20 or newer.

For how sign-in, the catalogue and playback work, see `plugin.video.tennistv: how playback works` in the
repository `CLAUDE.md`.

## Menu

Replays and highlights are grouped by content type: Match Highlights, Extended Highlights, Daily Highlights,
Short Highlights, Hot Shots, Replays, Features, Interviews and Doubles. Each is a paginated, newest-first list.

Not yet implemented (future work): browse by tournament/year, Players, Live events, Search and Watchlist.

## Development

Exercise the API outside Kodi with the smoke test (uses the shim in `tests/shim`):

```sh
python plugin.video.tennistv/tests/smoke.py            # public catalogue checks only
python plugin.video.tennistv/tests/smoke.py --login    # device-code sign in, then test playback
```

Sign in prints a URL and code to authorise in a browser; the session is cached in `tests/.userdata.json`.
