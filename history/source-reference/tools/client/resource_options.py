"""Change only the dedicated test client's optional Japanese resource preference."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote

from prepare_test_instance import PACKAGE, ROOT, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--japanese", action=argparse.BooleanOptionalAction, required=True)
    options = parser.parse_args()
    if command("shell", "getprop", "ro.serialno") != "test-device-example":
        raise RuntimeError("Unexpected test emulator identity")
    command("shell", "am", "force-stop", PACKAGE)
    path = f"/data/data/{PACKAGE}/shared_prefs/{PACKAGE}.v2.playerprefs.xml"
    original = command("shell", f"su -c 'cat {path}'")
    tree = ET.fromstring(original)
    setting = next(e for e in tree if e.attrib.get("name") == "key_hotupdate_res_setting")
    value = json.loads(unquote(setting.text))
    if set(value) - {"dyn_illust", "voice_basic", "voice_cn", "voice_jp", "voice_en", "voice_kr", "voice_custom"}:
        raise RuntimeError("Unrecognized resource options")
    value["voice_jp"] = int(options.japanese)
    setting.text = quote(json.dumps(value, separators=(",", ":")), safe="")
    record = ROOT / "data/client/test-instance"
    backup = record / "unity-resource-options.before.xml"
    if not backup.exists():
        backup.write_text(original, "utf-8")
    updated = record / "unity-resource-options.updated.xml"
    ET.ElementTree(tree).write(updated, encoding="utf-8", xml_declaration=True)
    package_info = command("shell", "dumpsys", "package", PACKAGE)
    uid = re.search(r"\buserId=(\d+)", package_info).group(1)
    command("push", str(updated), "/data/local/tmp/terralocal-resource-options.xml")
    script = (f"cp /data/local/tmp/terralocal-resource-options.xml {path}.terralocal-tmp && "
              f"chown {uid}:{uid} {path}.terralocal-tmp && chmod 600 {path}.terralocal-tmp && "
              f"mv {path}.terralocal-tmp {path}")
    command("shell", f"su -c '{script}'")
    verified = ET.fromstring(command("shell", f"su -c 'cat {path}'"))
    actual = next(e.text for e in verified if e.attrib.get("name") == "key_hotupdate_res_setting")
    if actual != setting.text:
        raise RuntimeError("Resource preference readback mismatch")
    print(f"Japanese resource selection: {options.japanese}; other preferences preserved")


if __name__ == "__main__":
    main()
