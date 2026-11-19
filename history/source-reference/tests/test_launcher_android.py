"""Fingerprint gates, bounded tools and scoped Android routing preflight."""
import hashlib
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest
from cryptography import x509

from terralocal.config import Settings
from terralocal.launcher import android
from terralocal.launcher.client_binding import (
    CAMPAIGN_CLIENT_PROFILE,
    CASH_CLIENT_PROFILE,
    CASH_PATCHED_APK,
    DEVICE_SERIAL,
    PACKAGE,
    PATCHED_APK,
    SERIAL,
    ClientBinding,
    expected_apk,
    installation_folder,
)
from terralocal.launcher.client_session import ClientConnectionError
from terralocal.server.compatibility.profile import ROGUE_CLIENT_PROFILE, ROGUE_DATA_HASH, native_profile
from terralocal.server.services.tls import ensure_certificate


@pytest.fixture
def transport(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", emulator_dir=tmp_path / "ld", game_port=18443,
                        advertised_url="https://127.0.0.1:8443", tls_dns_names=sorted(android.HOSTS),
                        gamedata_hash=android.FROZEN_DATA, client_profile="cn-android-2.7.71-display")
    settings.prepare()
    settings.emulator_dir.mkdir()
    for name in ("adb.exe", "ldconsole.exe"):
        (settings.emulator_dir / name).touch()
    receipt = settings.data_dir / "client/test-instance/installation.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"instance": 1, "name": "TerraLocal", "serial": SERIAL,
        "apk_sha256": PATCHED_APK, "resource_manifest": android.RESOURCE_INDEX,
        "official_authentication_copied": False}), "utf-8")
    profile = SimpleNamespace(package=PACKAGE, channel="official", client_version="2.7.71", version_code=190,
        apk_sha256=android.ORIGINAL_APK, resource_version="26-09-22-07-47-20_6c71fa", api_version="V070",
        gamedata_hash=android.FROZEN_DATA)
    monkeypatch.setattr(android.Bootstrap, "profile", lambda _self: profile)
    return android.AndroidTransport(settings, threading.Event())


def test_matching_configuration_accepts_only_prepared_local_https(transport):
    transport.validate_configuration()


def test_campaign_profile_requires_its_exact_new_data_and_separate_preparation(transport):
    legacy = transport.settings.data_dir / "client/test-instance/installation.json"
    original = legacy.read_bytes()
    transport.settings.client_profile = CAMPAIGN_CLIENT_PROFILE
    profile = android.Bootstrap(transport.settings).profile()
    # The old 18-table profile is not silently accepted for campaign QA.
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "UNSUPPORTED_CLIENT_PROFILE"
    profile.gamedata_hash = transport.settings.gamedata_hash = android.CAMPAIGN_DATA
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_NOT_PREPARED"
    receipt = legacy.parent.parent / installation_folder(CAMPAIGN_CLIENT_PROFILE) / "installation.json"
    receipt.parent.mkdir()
    value = json.loads(original)
    value["apk_sha256"] = CASH_PATCHED_APK
    receipt.write_text(json.dumps(value), "utf-8")
    transport.validate_configuration()
    assert legacy.read_bytes() == original
    assert expected_apk(CAMPAIGN_CLIENT_PROFILE) == CASH_PATCHED_APK
    assert installation_folder(CAMPAIGN_CLIENT_PROFILE) != installation_folder(CASH_CLIENT_PROFILE)
    assert native_profile(CAMPAIGN_CLIENT_PROFILE) == "cn-android-2.7.71-display"
    assert native_profile("unknown-future-profile") == "unknown-future-profile"


def test_rogue_profile_requires_exact_data_and_its_own_sdk3_receipt(transport):
    legacy = transport.settings.data_dir / "client/test-instance/installation.json"
    original = legacy.read_bytes()
    transport.settings.client_profile = ROGUE_CLIENT_PROFILE
    profile = android.Bootstrap(transport.settings).profile()
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "UNSUPPORTED_CLIENT_PROFILE"
    profile.gamedata_hash = transport.settings.gamedata_hash = ROGUE_DATA_HASH
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_NOT_PREPARED"
    folder = installation_folder(ROGUE_CLIENT_PROFILE)
    assert folder == "test-instance-rogue-qa"
    assert folder not in {installation_folder(CAMPAIGN_CLIENT_PROFILE), installation_folder(CASH_CLIENT_PROFILE)}
    receipt = legacy.parent.parent / folder / "installation.json"
    receipt.parent.mkdir()
    value = json.loads(original)
    receipt.write_text(json.dumps(value), "utf8")
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_RECEIPT_MISMATCH"
    value["apk_sha256"] = CASH_PATCHED_APK
    receipt.write_text(json.dumps(value), "utf8")
    transport.validate_configuration()
    assert expected_apk(ROGUE_CLIENT_PROFILE) == CASH_PATCHED_APK
    assert legacy.read_bytes() == original


@pytest.mark.parametrize("profile_id,wrong_data", [
    (ROGUE_CLIENT_PROFILE, android.CAMPAIGN_DATA), (CAMPAIGN_CLIENT_PROFILE, ROGUE_DATA_HASH),
    ("cn-android-2.7.71-display", ROGUE_DATA_HASH), (CASH_CLIENT_PROFILE, ROGUE_DATA_HASH),
    ("unknown-future-profile", ROGUE_DATA_HASH),
])
def test_rogue_and_campaign_data_are_not_interchangeable(transport, profile_id, wrong_data, monkeypatch):
    transport.settings.client_profile = profile_id
    profile = android.Bootstrap(transport.settings).profile()
    profile.gamedata_hash = transport.settings.gamedata_hash = wrong_data
    calls = []
    monkeypatch.setattr(transport, "_run", lambda *_args, **_kwargs: calls.append(True))
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "UNSUPPORTED_CLIENT_PROFILE" and not calls


@pytest.mark.parametrize("wrong", [PATCHED_APK, "0" * 64])
def test_rogue_binding_rejects_old_or_unrecognized_binary(transport, wrong):
    binding = ClientBinding(account_id=1, account_uid="synthetic", client_profile=ROGUE_CLIENT_PROFILE,
                            gamedata_hash=ROGUE_DATA_HASH, apk_sha256=wrong)
    with pytest.raises(ClientConnectionError) as error:
        binding.validate_target()
    assert error.value.code == "UNSUPPORTED_CLIENT_BINDING"


@pytest.mark.parametrize("profile_id", ["cn-android-2.7.71-display", CASH_CLIENT_PROFILE, "unknown-future-profile"])
def test_campaign_hash_is_not_a_global_data_allowlist(transport, profile_id):
    transport.settings.client_profile = profile_id
    profile = android.Bootstrap(transport.settings).profile()
    profile.gamedata_hash = transport.settings.gamedata_hash = android.CAMPAIGN_DATA
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "UNSUPPORTED_CLIENT_PROFILE"


@pytest.mark.parametrize("wrong", [PATCHED_APK, "0" * 64])
def test_campaign_binding_rejects_unmatched_binary(transport, wrong):
    binding = ClientBinding(account_id=1, account_uid="synthetic", client_profile=CAMPAIGN_CLIENT_PROFILE,
                            gamedata_hash=android.CAMPAIGN_DATA, apk_sha256=wrong)
    with pytest.raises(ClientConnectionError) as error:
        binding.validate_target()
    assert error.value.code == "UNSUPPORTED_CLIENT_BINDING"


def test_cash_adapter_uses_separate_receipt_and_rejects_old_fingerprint(transport):
    legacy = transport.settings.data_dir / "client/test-instance/installation.json"
    before = legacy.read_bytes()
    transport.settings.client_profile = CASH_CLIENT_PROFILE
    receipt = transport.settings.data_dir / "client/test-instance-local-cash/installation.json"
    receipt.parent.mkdir()
    receipt.write_bytes(before)
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_RECEIPT_MISMATCH"
    value = json.loads(before)
    value["apk_sha256"] = CASH_PATCHED_APK
    receipt.write_text(json.dumps(value), "utf-8")
    transport.validate_configuration()
    assert legacy.read_bytes() == before
    binding = ClientBinding(account_id=1, account_uid="synthetic", client_profile=CASH_CLIENT_PROFILE,
                            gamedata_hash=android.FROZEN_DATA, apk_sha256=PATCHED_APK)
    with pytest.raises(ClientConnectionError):
        binding.validate_target()
    binding.apk_sha256 = CASH_PATCHED_APK
    binding.validate_target()


def test_cached_identity_cannot_bypass_new_adapter_fingerprint(transport, monkeypatch):
    digest = [PATCHED_APK]
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        values = {
            ("shell", "getprop", "ro.serialno"): DEVICE_SERIAL,
            ("shell", "cat", "/proc/sys/kernel/random/boot_id"): "12345678-1234-1234-1234-123456789012",
            ("shell", "pm", "path", PACKAGE): "package:/data/app/local/base.apk",
            ("shell", "dumpsys", "package", PACKAGE): "userId=10077\nlastUpdateTime=2026-10-11",
            ("shell", "sha256sum", "/data/app/local/base.apk"): digest[0] + "  /data/app/local/base.apk",
            ("shell", "test", "-f", f"{android.FILES}/Bundles/{android.RESOURCE_INDEX}"): "",
        }
        return values[args]

    monkeypatch.setattr(transport, "command", command)
    monkeypatch.setattr(transport, "root", lambda *_args, **_kwargs: "uid=0(root)")
    transport.identify()
    transport.identify()
    transport.settings.client_profile = CASH_CLIENT_PROFILE
    with pytest.raises(ClientConnectionError) as error:
        transport.identify()
    assert error.value.code == "UNSUPPORTED_CLIENT_APK"
    digest[0] = CASH_PATCHED_APK
    transport.identify()
    assert sum(c[:2] == ("shell", "sha256sum") for c in calls) == 3


@pytest.mark.parametrize("change", [
    {"instance": 0}, {"instance": True}, {"serial": "emulator-5554"}, {"apk_sha256": "0" * 64},
    {"resource_manifest": "other.idx"}, {"official_authentication_copied": True},
])
def test_wrong_receipt_is_rejected_before_device_commands(transport, monkeypatch, change):
    path = transport.settings.data_dir / "client/test-instance/installation.json"
    receipt = json.loads(path.read_bytes())
    path.write_text(json.dumps({**receipt, **change}), "utf-8")
    calls = []
    monkeypatch.setattr(transport, "_run", lambda *_args, **_kwargs: calls.append(True))
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_RECEIPT_MISMATCH" and not calls


@pytest.mark.parametrize("field,value", [
    ("emulator_index", 0), ("advertised_url", "https://192.0.2.1:8443"), ("tls", False),
    ("tls_dns_names", []), ("game_host", "192.0.2.1"),
    ("advertised_url", "https://127.0.0.1:8443/path"), ("advertised_url", "https://127.0.0.1:8443/?q=1"),
])
def test_unsupported_routing_never_runs_android_tool(transport, monkeypatch, field, value):
    setattr(transport.settings, field, value)
    calls = []
    monkeypatch.setattr(transport, "_run", lambda *_args, **_kwargs: calls.append(True))
    with pytest.raises(ClientConnectionError) as error:
        transport.validate_configuration()
    assert error.value.code == "CLIENT_ROUTING_CONFIG" and not calls


def test_original_instance_identity_is_rejected_before_other_reads_or_writes(transport, monkeypatch):
    calls = []

    def command(*args, **_kwargs):
        calls.append(args)
        return "another-device"

    monkeypatch.setattr(transport, "command", command)
    with pytest.raises(ClientConnectionError) as error:
        transport.identify()
    assert error.value.code == "EMULATOR_IDENTITY_MISMATCH"
    assert calls == [("shell", "getprop", "ro.serialno")]


def test_unknown_apk_fingerprint_never_reaches_root_or_resource_delivery(transport, monkeypatch):
    calls, roots = [], []

    def command(*args, **_kwargs):
        calls.append(args)
        return {
            ("shell", "getprop", "ro.serialno"): DEVICE_SERIAL,
            ("shell", "cat", "/proc/sys/kernel/random/boot_id"): "12345678-1234-1234-1234-123456789012",
            ("shell", "pm", "path", PACKAGE): "package:/data/app/local/base.apk",
            ("shell", "dumpsys", "package", PACKAGE): "userId=10077\nlastUpdateTime=2026-10-11",
            ("shell", "sha256sum", "/data/app/local/base.apk"): "0" * 64 + "  /data/app/local/base.apk",
        }[args]

    monkeypatch.setattr(transport, "command", command)
    monkeypatch.setattr(transport, "root", lambda *_args, **_kwargs: roots.append(True))
    with pytest.raises(ClientConnectionError) as error:
        transport.identify()
    assert error.value.code == "UNSUPPORTED_CLIENT_APK" and not roots
    assert len(calls) == 5


def test_root_has_atomic_device_guard_and_rejects_quote_escape(transport, monkeypatch):
    calls = []
    monkeypatch.setattr(transport, "command", lambda *args, **_kwargs: calls.append(args))
    transport.root("iptables -N TL_OFFLINE")
    assert calls == [("shell", "su -c '[ \"$(getprop ro.serialno)\" = \"test-device-example\" ] || exit 97; "
                      "iptables -N TL_OFFLINE'")]
    with pytest.raises(ClientConnectionError):
        transport.root("echo 'escape'")
    assert len(calls) == 1


def test_boot_launch_is_throttled_and_only_targets_instance_one(transport, monkeypatch):
    at = [100.0]
    calls = []
    monkeypatch.setattr(android.time, "monotonic", lambda: at[0])

    def run(executable, args, **_kwargs):
        calls.append(args)
        return "0,Original,0,0,0,-1,-1\n1,TerraLocal,0,0,0,-1,-1" if args == ("list2",) else ""

    monkeypatch.setattr(transport, "_run", run)
    for _ in range(3):
        with pytest.raises(ClientConnectionError, match="正在启动"):
            transport.ensure_running()
    assert calls.count(("launch", "--index", "1")) == 1
    at[0] += 31
    with pytest.raises(ClientConnectionError):
        transport.ensure_running()
    assert calls.count(("launch", "--index", "1")) == 2
    assert all("0" not in args for args in calls)


def test_tool_timeout_and_failure_are_sanitized_and_home_stays_in_data(transport, monkeypatch):
    observed = []
    monkeypatch.setattr(transport._adb_server, "ensure", lambda: 45678)

    def fail(args, **kwargs):
        observed.append(kwargs)
        raise subprocess.TimeoutExpired(args, 8, output="synthetic-private-output")

    monkeypatch.setattr(android.subprocess, "run", fail)
    with pytest.raises(ClientConnectionError) as error:
        transport.command("shell", "synthetic-private-command")
    assert error.value.code == "EMULATOR_TIMEOUT" and "synthetic-private" not in str(error.value)
    assert observed[0]["timeout"] == 8
    assert observed[0]["env"]["ANDROID_USER_HOME"] == str(transport.settings.data_dir / "launcher-client/adb-home")
    monkeypatch.setattr(android.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=1, stdout="synthetic-private-output", stderr="synthetic-private-error"))
    assert transport.command("shell", "id", probe=True) is None
    with pytest.raises(ClientConnectionError) as error:
        transport.command("shell", "id")
    assert "synthetic-private" not in str(error.value)


def test_adb_commands_ignore_foreign_socket_and_timeout_reaps_only_owned_server(transport, monkeypatch):
    calls, closed = [], []
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:192.0.2.1:5037")
    monkeypatch.setattr(transport._adb_server, "ensure", lambda: 45678)
    monkeypatch.setattr(transport._adb_server, "close", lambda: closed.append(True))

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        raise subprocess.TimeoutExpired(argv, 8)

    monkeypatch.setattr(android.subprocess, "run", run)
    with pytest.raises(ClientConnectionError) as error:
        transport.command("shell", "id")
    assert error.value.code == "EMULATOR_TIMEOUT" and closed == [True]
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [str(transport.adb), "-H", "127.0.0.1", "-P", "45678", "-s", SERIAL, "shell", "id"]
    assert "ADB_SERVER_SOCKET" not in options["env"] and options["timeout"] == 8
    assert "kill-server" not in argv


def test_foreign_hosts_mount_is_rejected_before_privileged_changes(transport, monkeypatch):
    ensure_certificate(transport.settings)
    roots = []
    monkeypatch.setattr(transport, "command", lambda *args, **_kwargs:
        "tmpfs /system/etc/hosts tmpfs rw 0 0" if args[-1] == "/proc/mounts" else "127.0.0.1 localhost")
    monkeypatch.setattr(transport, "root", lambda *_args, **_kwargs: roots.append(True))
    with pytest.raises(ClientConnectionError) as error:
        transport.configure_routes(android.AndroidIdentity("boot", "/data/app/base.apk", 10077))
    assert error.value.code == "ANDROID_HOSTS_BUSY" and not roots
    assert not (transport.settings.data_dir / "launcher-client").exists()


def test_readiness_checks_cert_reverse_ipv4_ipv6_owner_and_nat(transport, monkeypatch):
    ensure_certificate(transport.settings)
    pem = (transport.settings.data_dir / "certs/ca.pem").read_text("utf-8")
    ca = x509.load_pem_x509_certificate(pem.encode())
    ca_name = f"{int.from_bytes(hashlib.md5(ca.subject.public_bytes()).digest()[:4], 'little'):08x}.0"
    state = {"ipv6": True, "reverse": True, "cert": True}

    def command(*args, **_kwargs):
        if args == ("reverse", "--list"):
            return "UsbFfs tcp:8443 tcp:18443" if state["reverse"] else ""
        if args[-1] == "/system/etc/hosts":
            return android.MARKER + "\n" + "\n".join(f"127.0.0.1 {host}" for host in android.HOSTS)
        if args[-1].endswith(ca_name):
            return pem if state["cert"] else "invalid"
        raise AssertionError("Unexpected routing read")

    def root(command, **_kwargs):
        if command == "iptables -S TL_OFFLINE":
            return "-N TL_OFFLINE\n-A TL_OFFLINE -d 127.0.0.0/8 -j RETURN\n-A TL_OFFLINE -j REJECT --reject-with icmp-port-unreachable"
        if command == "ip6tables -S TL_OFFLINE":
            return "-N TL_OFFLINE\n-A TL_OFFLINE -d ::1/128 -j RETURN\n-A TL_OFFLINE -j REJECT" if state["ipv6"] else ""
        if command == "iptables -t nat -S TL_HTTPS":
            return "-N TL_HTTPS\n-A TL_HTTPS -p tcp --dport 443 -j REDIRECT --to-ports 8443"
        if " -C " in command:
            return ""
        raise AssertionError("Unexpected routing rule")

    monkeypatch.setattr(transport, "command", command)
    monkeypatch.setattr(transport, "root", root)
    identity = android.AndroidIdentity("boot", "/data/app/base.apk", 10077)
    assert transport.routes_ready(identity)
    for key in state:
        state[key] = False
        assert not transport.routes_ready(identity)
        state[key] = True


def test_callback_delivery_uses_temporary_rename_and_checks_result(transport, tmp_path, monkeypatch):
    path = tmp_path / "terralocal-login.json"
    path.write_text("{}", "utf-8")
    calls = []
    monkeypatch.setattr(transport, "command", lambda *args, **_kwargs: calls.append(args))
    monkeypatch.setattr(transport, "file_matches", lambda *_args: False)
    with pytest.raises(ClientConnectionError) as error:
        transport.deliver("terralocal-login.json", path)
    assert error.value.code == "CLIENT_FILE_DELIVERY_FAILED"
    assert calls == [("shell", "mkdir", "-p", android.FILES),
                     ("push", str(path), f"{android.FILES}/terralocal-login.json.tmp"),
                     ("shell", "mv", f"{android.FILES}/terralocal-login.json.tmp",
                      f"{android.FILES}/terralocal-login.json")]
    with pytest.raises(ClientConnectionError):
        transport.deliver("arbitrary-file", path)
    assert len(calls) == 3
