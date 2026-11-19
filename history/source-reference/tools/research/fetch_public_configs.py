"""Freeze public bootstrap documents; never contacts authentication endpoints."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2] / "data" / "client" / "bootstrap" / "cn-android-2.7.71"
URLS = {
    "network": "https://ak-conf.hypergryph.com/config/prod/official/network_config",
    "network_android": "https://game-config.hypergryph.com/api/remote_config/1/prod/default/Android/network_config",
    "remote_android": "https://game-config.hypergryph.com/api/remote_config/1/prod/default/Android/remote_config",
    "sdk_app": "https://as.hypergryph.com/app/v1/config?appCode=7318def77669979d",
    "gate_android": "https://ak-webview.hypergryph.com/api/gate/meta/Android",
    "version": "https://ak-conf.hypergryph.com/config/prod/official/Android/version",
    "remote": "https://ak-conf.hypergryph.com/config/prod/official/remote_config",
    "preannouncement": "https://ak-conf.hypergryph.com/config/prod/announce_meta/Android/preannouncement.meta.json",
    "announcement": "https://ak-conf.hypergryph.com/config/prod/announce_meta/Android/announcement.meta.json",
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    existing = ROOT / "sources.json"
    manifest = json.loads(existing.read_bytes()) if existing.exists() else {}
    for name, url in URLS.items():
        target = ROOT / f"{name}.json"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != manifest.get(name, {}).get("sha256"):
                raise RuntimeError(f"Frozen document fingerprint mismatch: {name}")
            print(json.dumps({"document": name, "status": "retained-frozen"}))
            continue
        with urlopen(url, timeout=30) as response:
            body = response.read(4 * 1024 * 1024)
        json.loads(body)
        target.write_bytes(body)
        manifest[name] = {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
        print(json.dumps({"document": name, "size": len(body)}, ensure_ascii=False))
    (ROOT / "sources.json").write_text(json.dumps(manifest, indent=2), "utf-8")


if __name__ == "__main__":
    main()
