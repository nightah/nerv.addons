#!/usr/bin/env python3
"""Vendor ATP player headshots for plugin.video.tennistv.

The headshots live on atptour.com behind a Cloudflare bot challenge that a plain HTTP client
(curl, Kodi's image loader) cannot pass, so they can only be fetched by a real browser. This is a
two-step, mostly automated flow:

  1) python3 vendor.py --harvester
     Prints a JavaScript snippet with the current player sids baked in. Open any headshot URL such
     as https://www.atptour.com/-/media/alias/player-headshot/S0AG in Chrome (so the page is on the
     atptour.com origin with Cloudflare cleared), open the DevTools console, paste the snippet and
     click the COPY BUNDLE button it adds. It fetches every headshot and copies a JSON bundle
     ({sid: base64 png}) to the clipboard.

  2) pbpaste | python3 vendor.py --install
     Reads the bundle from stdin, resizes and compresses each headshot and writes it to
     plugin.video.tennistv/resources/media/players/<sid>.png, pruning players no longer listed.

Requires: sips (macOS, built in) and pngquant (brew install pngquant).
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

BIO_URL = "https://api.tennistv.com/content/atpmedia/BIO/EN?pageSize=200"
MEDIA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "plugin.video.tennistv", "resources", "media", "players")
)
DIM = 160
COLORS = 64


def _sids():
    out = subprocess.run(
        ["curl", "-sf", "--max-time", "40", BIO_URL, "-H", "account: atpmedia", "-H", "User-Agent: Mozilla/5.0"],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(out.stdout)
    sids = []
    for bio in data.get("content", []):
        refs = bio.get("references") or []
        sid = next((r.get("sid") for r in refs if r.get("type") == "ATP_PLAYER" and r.get("sid")), None)
        if sid:
            sids.append(sid)
    return sids


HARVESTER = """// Paste on an https://www.atptour.com/-/media/alias/player-headshot/<sid> page, then click COPY BUNDLE.
const SIDS=__SIDS__;
async function one(sid){for(let a=0;a<2;a++){try{
  const r=await fetch(`https://www.atptour.com/-/media/alias/player-headshot/${sid}`);
  if(!r.ok)throw 0;
  const buf=new Uint8Array(await r.arrayBuffer());
  let s='';for(let i=0;i<buf.length;i++)s+=String.fromCharCode(buf[i]);
  return {sid,b64:btoa(s)};
}catch(e){if(a)return{sid,err:1};await new Promise(r=>setTimeout(r,400));}}}
(async()=>{
  const out={},failed=[];
  for(let i=0;i<SIDS.length;i+=8){const b=await Promise.all(SIDS.slice(i,i+8).map(one));
    for(const x of b){if(x.b64)out[x.sid]=x.b64;else failed.push(x.sid);}}
  window.__data=JSON.stringify(out);
  document.querySelectorAll('#cpbtn').forEach(e=>e.remove());
  const btn=document.createElement('button');btn.id='cpbtn';
  btn.textContent=`COPY BUNDLE (${Object.keys(out).length}, failed ${failed.length})`;
  btn.style.cssText='position:fixed;top:20px;left:20px;z-index:2147483647;padding:20px 30px;'
    +'background:#06c;color:#fff;font:bold 24px sans-serif;border:4px solid #000;cursor:pointer;';
  btn.onclick=async()=>{await navigator.clipboard.writeText(window.__data);
    btn.textContent='COPIED '+window.__data.length;btn.style.background='#0a0';};
  document.body.appendChild(btn);
})();"""


def _harvester():
    sids = json.dumps(_sids(), separators=(",", ":"))
    print(HARVESTER.replace("__SIDS__", sids))


def _install(bundle):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        for sid, b64 in bundle.items():
            src = os.path.join(tmp, f"{sid}.src.png")
            sized = os.path.join(tmp, f"{sid}.sized.png")
            dst = os.path.join(MEDIA_DIR, f"{sid}.png")
            with open(src, "wb") as f:
                f.write(base64.b64decode(b64))
            subprocess.run(["sips", "-Z", str(DIM), src, "--out", sized], check=True, capture_output=True)
            subprocess.run(["pngquant", str(COLORS), "--speed", "1", "--force", "--output", dst, sized], check=True)
            written.append(sid)

    # Prune headshots for players no longer in the bundle.
    kept = {f"{sid}.png" for sid in written}
    pruned = [f for f in os.listdir(MEDIA_DIR) if f.endswith(".png") and f not in kept]
    for f in pruned:
        os.remove(os.path.join(MEDIA_DIR, f))

    total = sum(os.path.getsize(os.path.join(MEDIA_DIR, f"{sid}.png")) for sid in written)
    print(f"wrote {len(written)} headshots ({total / 1024:.0f} KB), pruned {len(pruned)} -> {MEDIA_DIR}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--harvester", action="store_true", help="print the browser harvester snippet")
    group.add_argument("--install", action="store_true", help="install the bundle read from stdin")
    args = ap.parse_args()

    if args.harvester:
        _harvester()
    else:
        _install(json.load(sys.stdin))


if __name__ == "__main__":
    main()
