"""Build an APK-fingerprint-specific, static local login/purchase adapter.

No official APK/assets are redistributed. Candidate outputs stay in data/client/patch.
This tool never installs anything or alters emulator data. Client validation is separate.
"""

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_APK = "0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db"
ADAPTER = "cn-2.7.71-static-sdk-v3"
BODY = """    .locals 6
    :try_start
    invoke-static {}, Lcom/u8/sdk/U8SDK;->getInstance()Lcom/u8/sdk/U8SDK;
    move-result-object v0
    invoke-virtual {v0}, Lcom/u8/sdk/U8SDK;->getContext()Landroid/app/Activity;
    move-result-object v1
    const/4 v2, 0x0
    invoke-virtual {v1, v2}, Landroid/app/Activity;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v1
    new-instance v2, Ljava/io/File;
    const-string v3, "terralocal-login.json"
    invoke-direct {v2, v1, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V
    invoke-virtual {v2}, Ljava/io/File;->toPath()Ljava/nio/file/Path;
    move-result-object v1
    invoke-static {v1}, Ljava/nio/file/Files;->readAllBytes(Ljava/nio/file/Path;)[B
    move-result-object v1
    new-instance v2, Ljava/lang/String;
    sget-object v3, Ljava/nio/charset/StandardCharsets;->UTF_8:Ljava/nio/charset/Charset;
    invoke-direct {v2, v1, v3}, Ljava/lang/String;-><init>([BLjava/nio/charset/Charset;)V
    invoke-virtual {v0, v2}, Lcom/u8/sdk/U8SDK;->onLoginResult(Ljava/lang/String;)V
    :try_end
    return-void
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :failed
    :failed
    move-exception v0
    invoke-static {}, Lcom/u8/sdk/U8SDK;->getInstance()Lcom/u8/sdk/U8SDK;
    move-result-object v0
    const/4 v1, 0x5
    const-string v2, "TerraLocal: bind a local account in the launcher first"
    invoke-virtual {v0, v1, v2}, Lcom/u8/sdk/U8SDK;->onResult(ILjava/lang/String;)V
    return-void
"""

# Only the updater's latest-version query is adapted. Normal resource loading,
# signature checking of the network document and game calls remain intact.
UPDATE_BODY = r'''    .locals 5
    :try_start
    sget-object v0, Lcom/hypergryph/gameupdate/core/GameUpdateGlobalContext;->INSTANCE:Lcom/hypergryph/gameupdate/core/GameUpdateGlobalContext;
    invoke-virtual {v0}, Lcom/hypergryph/gameupdate/core/GameUpdateGlobalContext;->getApplication()Landroid/content/Context;
    move-result-object v0
    const/4 v1, 0x0
    invoke-virtual {v0, v1}, Landroid/content/Context;->getExternalFilesDir(Ljava/lang/String;)Ljava/io/File;
    move-result-object v0
    new-instance v1, Ljava/io/File;
    const-string v2, "terralocal-update.json"
    invoke-direct {v1, v0, v2}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V
    invoke-virtual {v1}, Ljava/io/File;->toPath()Ljava/nio/file/Path;
    move-result-object v0
    invoke-static {v0}, Ljava/nio/file/Files;->readAllBytes(Ljava/nio/file/Path;)[B
    move-result-object v0
    new-instance v1, Ljava/lang/String;
    sget-object v2, Ljava/nio/charset/StandardCharsets;->UTF_8:Ljava/nio/charset/Charset;
    invoke-direct {v1, v0, v2}, Ljava/lang/String;-><init>([BLjava/nio/charset/Charset;)V
    invoke-interface {p0, v1}, Lcom/hypergryph/nativebridge/HGNativeCallback;->onResult(Ljava/lang/String;)V
    :try_end
    return-void
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :failed
    :failed
    move-exception v0
    const-string v1, "{\"code\":1103,\"version\":\"\",\"action\":0,\"updateType\":0,\"updateInfo\":\"\",\"state\":0}"
    invoke-interface {p0, v1}, Lcom/hypergryph/nativebridge/HGNativeCallback;->onResult(Ljava/lang/String;)V
    return-void
'''

# HGPay is the frozen plugin's payment entry. Only a local server's TL quote
# reaches success; neither branch invokes HGSDK/HGSDKBridge or financial APIs.
# U8's C# consumer expects extension as a string, not a nested JSON object.
PAY_BODY = r'''    .locals 7
    :try_start
    invoke-virtual {p1}, Lcom/u8/sdk/PayParams;->getOrderID()Ljava/lang/String;
    move-result-object v0
    const-string v1, "TL-"
    invoke-virtual {v0, v1}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z
    move-result v1
    if-eqz v1, :failed
    invoke-virtual {p1}, Lcom/u8/sdk/PayParams;->getExtension()Ljava/lang/String;
    move-result-object v1
    new-instance v2, Lorg/json/JSONObject;
    invoke-direct {v2, v1}, Lorg/json/JSONObject;-><init>(Ljava/lang/String;)V
    const-string v3, "terralocal"
    invoke-virtual {v2, v3}, Lorg/json/JSONObject;->getBoolean(Ljava/lang/String;)Z
    move-result v3
    if-eqz v3, :failed
    const-string v3, "orderId"
    invoke-virtual {v2, v3}, Lorg/json/JSONObject;->getString(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    invoke-virtual {v0, v3}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :failed
    const-string v3, "goodId"
    invoke-virtual {v2, v3}, Lorg/json/JSONObject;->getString(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    invoke-virtual {p1}, Lcom/u8/sdk/PayParams;->getProductId()Ljava/lang/String;
    move-result-object v4
    invoke-virtual {v3, v4}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v3
    if-eqz v3, :failed
    const-string v3, "receipt"
    invoke-virtual {v2, v3}, Lorg/json/JSONObject;->getString(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3
    const-string v4, "[A-Za-z0-9_-]{43}"
    invoke-virtual {v3, v4}, Ljava/lang/String;->matches(Ljava/lang/String;)Z
    move-result v3
    if-eqz v3, :failed
    new-instance v2, Lorg/json/JSONObject;
    invoke-direct {v2}, Lorg/json/JSONObject;-><init>()V
    const-string v3, "status"
    const/4 v4, 0x0
    invoke-virtual {v2, v3, v4}, Lorg/json/JSONObject;->put(Ljava/lang/String;I)Lorg/json/JSONObject;
    const-string v3, "outTradeNo"
    invoke-virtual {v2, v3, v0}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    const-string v3, "extension"
    invoke-virtual {v2, v3, v1}, Lorg/json/JSONObject;->put(Ljava/lang/String;Ljava/lang/Object;)Lorg/json/JSONObject;
    invoke-virtual {v2}, Lorg/json/JSONObject;->toString()Ljava/lang/String;
    move-result-object v2
    invoke-static {}, Lcom/u8/sdk/U8SDK;->getInstance()Lcom/u8/sdk/U8SDK;
    move-result-object v0
    const/16 v1, 0xa
    invoke-virtual {v0, v1, v2}, Lcom/u8/sdk/U8SDK;->onResult(ILjava/lang/String;)V
    :try_end
    return-void
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :caught
    :caught
    move-exception v0
    :failed
    invoke-static {}, Lcom/u8/sdk/U8SDK;->getInstance()Lcom/u8/sdk/U8SDK;
    move-result-object v0
    const/16 v1, 0xb
    const-string v2, "{\"status\":1,\"message\":\"TerraLocal local purchase requires a valid server quote\"}"
    invoke-virtual {v0, v1, v2}, Lcom/u8/sdk/U8SDK;->onResult(ILjava/lang/String;)V
    return-void
'''


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


def signing_key(directory):
    key_path, cert_path = directory / "signing-key.der", directory / "signing-cert.der"
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path
    previous = directory.parent / "cn-2.7.71-static-sdk-v2"
    if (previous / key_path.name).exists() and (previous / cert_path.name).exists():
        shutil.copyfile(previous / key_path.name, key_path)
        shutil.copyfile(previous / cert_path.name, cert_path)
        return key_path, cert_path
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TerraLocal Local Client")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650)).sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    return key_path, cert_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    if sha(args.apk) != EXPECTED_APK:
        raise ValueError("Unsupported APK fingerprint; no changes performed")
    directory = ROOT / "data" / "client" / "patch" / ADAPTER
    if (directory / "manifest.json").exists() or (directory / "TerraLocal-client.apk").exists():
        raise ValueError("保留已生成的适配版本；不能覆盖既有客户端或其验证记录")
    directory.mkdir(parents=True, exist_ok=True)
    jar = ROOT / "tools" / "local" / "jadx" / "lib" / "jadx-1.5.3-all.jar"
    java = ["java", "-Xmx1024m", f"-Djava.io.tmpdir={ROOT / '.cache' / 'tmp'}", "-cp", jar]
    dex, modified = directory / "original.dex", directory / "local.dex"
    with ZipFile(args.apk) as archive:
        dex.write_bytes(archive.read("classes.dex"))
    smali = directory / "smali"
    run([*java, "com.android.tools.smali.baksmali.Main", "disassemble", dex, "--output", smali])
    path = smali / "com" / "u8" / "sdk" / "HGUser.smali"
    source = path.read_text("utf-8")
    for signature in ("login()V", "loginCustom(Ljava/lang/String;)V"):
        pattern = r"(?m)^\.method public " + re.escape(signature) + r"\r?\n.*?^\.end method"
        replacement = ".method public " + signature + "\n" + BODY + ".end method"
        source, count = re.subn(pattern, replacement, source, flags=re.DOTALL)
        if count != 1:
            raise ValueError(f"APK method shape differs: {signature}")
    path.write_text(source, "utf-8")
    pay_path = smali / "com/u8/sdk/HGPay.smali"
    signature = "pay(Lcom/u8/sdk/PayParams;)V"
    pattern = r"(?m)^\.method public " + re.escape(signature) + r"\r?\n.*?^\.end method"
    replacement = ".method public " + signature + "\n" + PAY_BODY + ".end method"
    source, count = re.subn(pattern, lambda _: replacement, pay_path.read_text("utf-8"), flags=re.DOTALL)
    if count != 1:
        raise ValueError("APK cash callback method shape differs")
    pay_path.write_text(source, "utf-8")
    run([*java, "com.android.tools.smali.smali.Main", "assemble", smali, "--output", modified])
    update_dex, update_modified = directory / "original-update.dex", directory / "local-update.dex"
    with ZipFile(args.apk) as archive:
        update_dex.write_bytes(archive.read("classes5.dex"))
    update_smali = directory / "smali-update"
    run([*java, "com.android.tools.smali.baksmali.Main", "disassemble", update_dex, "--output", update_smali])
    update_path = update_smali / "com/hypergryph/gameupdate/GameUpdateSdk.smali"
    signature = "queryLatestGameUpdateInfo(Lcom/hypergryph/nativebridge/HGNativeCallback;)V"
    pattern = r"(?m)^\.method public static final " + re.escape(signature) + r"\r?\n.*?^\.end method"
    replacement = ".method public static final " + signature + "\n" + UPDATE_BODY + ".end method"
    source, count = re.subn(pattern, lambda _: replacement, update_path.read_text("utf-8"), flags=re.DOTALL)
    if count != 1:
        raise ValueError("APK update query shape differs")
    update_path.write_text(source, "utf-8")
    run([*java, "com.android.tools.smali.smali.Main", "assemble", update_smali, "--output", update_modified])
    unsigned, signed = directory / "local-unsigned.apk", directory / "TerraLocal-client.apk"
    with ZipFile(args.apk) as original, ZipFile(unsigned, "w") as target:
        for info in original.infolist():
            name = info.filename
            if name.startswith("META-INF/") and (name.endswith((".SF", ".RSA", ".DSA", ".EC"))
                                                   or name == "META-INF/MANIFEST.MF"):
                continue
            data = (modified.read_bytes() if name == "classes.dex" else
                    update_modified.read_bytes() if name == "classes5.dex" else None)
            info.extra = b""
            if info.compress_type == ZIP_STORED:
                alignment = 4096 if name.startswith("lib/") and name.endswith(".so") else 4
                offset = target.fp.tell() + 30 + len(name.encode("utf-8"))
                padding = (-offset) % alignment
                if padding:
                    if padding < 4:
                        padding += alignment
                    info.extra = struct.pack("<HH", 0xD935, padding - 4) + b"\0" * (padding - 4)
            if data is not None:
                target.writestr(info, data)
            else:
                with original.open(name) as source, target.open(info, "w") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
    key, cert = signing_key(directory)
    classes = directory / "java"
    classes.mkdir(exist_ok=True)
    run(["javac", "-J-Xmx256m", "-cp", jar, "-d", classes, ROOT / "tools" / "client" / "ApkSignerTool.java"])
    run(["java", "-Xmx1024m", f"-Djava.io.tmpdir={ROOT / '.cache' / 'tmp'}", "-cp", str(jar) + ";" + str(classes),
         "ApkSignerTool", unsigned, signed, key, cert])
    manifest = {"adapter": ADAPTER, "source_apk_sha256": EXPECTED_APK,
                "source_dex_sha256": sha(dex), "modified_dex_sha256": sha(modified),
                "source_update_dex_sha256": sha(update_dex), "modified_update_dex_sha256": sha(update_modified),
                "output_apk_sha256": sha(signed), "client_verified": False,
                "changes": ["HGUser.login", "HGUser.loginCustom", "HGPay.pay:local-quotes-only",
                            "GameUpdateSdk.queryLatestGameUpdateInfo"],
                "login_file": "terralocal-login.json", "update_file": "terralocal-update.json"}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    print(json.dumps({"candidate": str(signed), "sha256": manifest["output_apk_sha256"],
                      "client_verified": False}))
    # The signed candidate has been verified and fingerprinted. This intermediate
    # APK duplicates every asset and can be reproduced from the preserved input.
    unsigned.unlink()


if __name__ == "__main__":
    main()
