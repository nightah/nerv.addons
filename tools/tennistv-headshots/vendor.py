#!/usr/bin/env python3
"""Vendor ATP player headshots and country flags for plugin.video.tennistv.

Headshots live on atptour.com behind a Cloudflare bot challenge that gates on the TLS fingerprint, so a
plain HTTP client (curl, Kodi's image loader) cannot fetch them; only a real browser can. The roster of
players to vendor is every entrant in this and last season's tournament draws, keyed by ATP sid.

  1) python3 vendor.py --harvester
     Prints a JavaScript snippet (with the roster sids baked in). Open any headshot URL such as
     https://www.atptour.com/-/media/alias/player-headshot/S0AG in Chrome (so the page is on the
     atptour.com origin with Cloudflare cleared), open the DevTools console and paste it. It fetches every
     headshot, then adds a COPY button: click it repeatedly to copy the bundle to the clipboard in batches
     (the full set is tens of MB, too large for one clipboard write).

  2) pbpaste > batchN.json   (once per COPY click), then:
     cat batch*.json | python3 vendor.py --install
     Reads the batches from stdin, resizes and compresses each headshot and writes it to
     resources/media/players/<sid>.png. Existing files not in the bundle (eg. legends) are kept.

  3) python3 vendor.py --flags
     Fetches a rectangular 4:3 PNG flag (flagcdn.com, public-domain Flagpedia artwork) for each of the
     roster's nationalities and writes it to resources/media/flags/<code>.png, keyed by the ATP's IOC code.
     (The Tennis TV site's own flags are circle-cropped, which the overlay does not want.)

Requires: sips (macOS) and pngquant (brew install pngquant) for headshots.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(__file__)
PLAYERS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "plugin.video.tennistv/resources/media/players"))
FLAGS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "plugin.video.tennistv/resources/media/flags"))
API = "https://api.tennistv.com/tennis/v1"
FLAG_PNG = "https://flagcdn.com/48x36/{iso}.png"
# ATP nationalities are IOC codes; flagcdn is keyed by ISO 3166-1 alpha-2.
IOC_ISO = {
    "alg": "dz",
    "and": "ad",
    "ant": "ag",
    "arg": "ar",
    "arm": "am",
    "aus": "au",
    "aut": "at",
    "aze": "az",
    "bah": "bs",
    "bar": "bb",
    "bel": "be",
    "bih": "ba",
    "bol": "bo",
    "bra": "br",
    "bul": "bg",
    "can": "ca",
    "chi": "cl",
    "chn": "cn",
    "col": "co",
    "crc": "cr",
    "cro": "hr",
    "cyp": "cy",
    "cze": "cz",
    "den": "dk",
    "dom": "do",
    "ecu": "ec",
    "egy": "eg",
    "esa": "sv",
    "esp": "es",
    "est": "ee",
    "fin": "fi",
    "fra": "fr",
    "gbr": "gb",
    "geo": "ge",
    "ger": "de",
    "gre": "gr",
    "gua": "gt",
    "hkg": "hk",
    "hun": "hu",
    "ina": "id",
    "ind": "in",
    "irl": "ie",
    "isr": "il",
    "ita": "it",
    "jam": "jm",
    "jor": "jo",
    "jpn": "jp",
    "kaz": "kz",
    "kor": "kr",
    "lat": "lv",
    "lbn": "lb",
    "lie": "li",
    "ltu": "lt",
    "lux": "lu",
    "mar": "ma",
    "mda": "md",
    "mex": "mx",
    "mkd": "mk",
    "mlt": "mt",
    "mon": "mc",
    "mne": "me",
    "ned": "nl",
    "nor": "no",
    "nzl": "nz",
    "pak": "pk",
    "par": "py",
    "per": "pe",
    "phi": "ph",
    "pol": "pl",
    "por": "pt",
    "pur": "pr",
    "qat": "qa",
    "rou": "ro",
    "rsa": "za",
    "slo": "si",
    "srb": "rs",
    "sui": "ch",
    "svk": "sk",
    "swe": "se",
    "tha": "th",
    "tpe": "tw",
    "tun": "tn",
    "tur": "tr",
    "ukr": "ua",
    "uru": "uy",
    "usa": "us",
    "uzb": "uz",
    "ven": "ve",
    "vie": "vn",
    "zim": "zw",
}
SEASONS = 2  # this season and last
DIM, COLORS = 160, 64


def _curl_json(url):
    out = subprocess.run(
        ["curl", "-sf", "--max-time", "30", url, "-H", "account: atpmedia", "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def _roster():
    # Every draw entrant across the recent seasons: {sid: three-letter-nationality}.
    from datetime import date

    players = {}
    for year in range(date.today().year, date.today().year - SEASONS, -1):
        tours = _curl_json(f"{API}/tournaments?from={year}-01-01&to={year}-12-31&size=250") or []
        tours = tours if isinstance(tours, list) else tours.get("content", [])
        for t in tours:
            if not t.get("id") or t.get("type") == "GS":
                continue
            draw = _curl_json(f"{API}/tournaments/{t['id']}/{year}/draws")
            if not isinstance(draw, dict):
                continue
            for event in draw.values():
                if not isinstance(event, dict):
                    continue
                for rnd in event.get("Rounds") or []:
                    for fx in rnd.get("Fixtures") or []:
                        for line in ("DrawLineTop", "DrawLineBottom"):
                            for p in (fx.get(line) or {}).get("Players") or []:
                                if p.get("PlayerId"):
                                    players.setdefault(p["PlayerId"], p.get("Nationality"))
                        res = fx.get("Result") or {}
                        for team in ("TeamTop", "TeamBottom"):
                            p = (res.get(team) or {}).get("Player") or {}
                            if p.get("PlayerId"):
                                players.setdefault(p["PlayerId"], p.get("Nationality"))
    return players


HARVESTER = """// Paste on an https://www.atptour.com/-/media/alias/player-headshot/<sid> page.
const SIDS=__SIDS__,D={};
async function one(sid){for(let a=0;a<3;a++){try{
  const r=await fetch(`https://www.atptour.com/-/media/alias/player-headshot/${sid}`);if(!r.ok)throw 0;
  const b=new Uint8Array(await r.arrayBuffer());let s='';for(let i=0;i<b.length;i++)s+=String.fromCharCode(b[i]);
  return btoa(s);}catch(e){if(a===2)return null;await new Promise(x=>setTimeout(x,500));}}}
(async()=>{
  for(let i=0;i<SIDS.length;i+=8){const b=await Promise.all(SIDS.slice(i,i+8).map(async s=>[s,await one(s)]));
    for(const[s,v]of b)if(v)D[s]=v;}
  const keys=Object.keys(D),SIZE=143;let bi=0;
  const total=Math.ceil(keys.length/SIZE);
  const btn=document.createElement('button');btn.textContent='COPY BATCH 1 of '+total;
  btn.style.cssText='position:fixed;top:20px;left:20px;z-index:2147483647;padding:20px 30px;'
    +'background:#06c;color:#fff;font:bold 24px sans-serif;border:4px solid #000;cursor:pointer';
  btn.onclick=()=>{const o={};for(const k of keys.slice(bi*SIZE,bi*SIZE+SIZE))o[k]=D[k];
    navigator.clipboard.writeText(JSON.stringify(o)).then(()=>{bi++;
      btn.textContent='COPIED '+bi+'/'+total+' - pbpaste, then click for next';btn.style.background='#0a0';});};
  document.body.appendChild(btn);
})();"""


def _harvester():
    sids = json.dumps(sorted(_roster()), separators=(",", ":"))
    print(HARVESTER.replace("__SIDS__", sids))


def _read_bundles():
    # The clipboard batches are concatenated on stdin as back-to-back JSON objects; merge them.
    text = sys.stdin.read().strip()
    decoder = json.JSONDecoder()
    bundle, i = {}, 0
    while i < len(text):
        obj, i = decoder.raw_decode(text, i)
        bundle.update(obj)
        while i < len(text) and text[i].isspace():
            i += 1
    return bundle


def _install(bundle):
    os.makedirs(PLAYERS_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for sid, b64 in bundle.items():
            src = os.path.join(tmp, "s.png")
            sized = os.path.join(tmp, "r.png")
            with open(src, "wb") as f:
                f.write(base64.b64decode(b64))
            subprocess.run(["sips", "-Z", str(DIM), src, "--out", sized], check=True, capture_output=True)
            subprocess.run(
                ["pngquant", str(COLORS), "--speed", "1", "--force", "--output", f"{PLAYERS_DIR}/{sid}.png", sized],
                check=True,
            )
    print(f"installed {len(bundle)} headshots -> {PLAYERS_DIR}")


def _flags():
    os.makedirs(FLAGS_DIR, exist_ok=True)
    codes = sorted({c.lower() for c in _roster().values() if c})
    ok, missing = 0, []
    for code in codes:
        iso = IOC_ISO.get(code)
        got = subprocess.run(["curl", "-sf", "--max-time", "15", FLAG_PNG.format(iso=iso)], capture_output=True)
        if not iso or got.returncode or not got.stdout.startswith(b"\x89PNG"):
            missing.append(code)
            continue
        with open(f"{FLAGS_DIR}/{code}.png", "wb") as f:
            f.write(got.stdout)
        ok += 1
    print(f"vendored {ok} flags -> {FLAGS_DIR}; no flag for: {' '.join(missing)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--harvester", action="store_true", help="print the browser headshot harvester")
    g.add_argument("--install", action="store_true", help="install headshot batches read from stdin")
    g.add_argument("--flags", action="store_true", help="vendor country flags for the roster")
    args = ap.parse_args()
    if args.harvester:
        _harvester()
    elif args.flags:
        _flags()
    else:
        _install(_read_bundles())


if __name__ == "__main__":
    main()
