"""Owned process lifetime and real loopback protocol readiness; no Android needed."""
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from terralocal.launcher import adb_server
from terralocal.launcher.client_session import ClientConnectionError


@pytest.fixture
def managed(tmp_path, monkeypatch):
    program = tmp_path / "authored_adb_fixture.py"
    program.write_text('''import json, socket, sys
from pathlib import Path
args = sys.argv[2:]
Path(sys.argv[1]).write_text(json.dumps(args))
mode = Path(sys.argv[1]).with_suffix('.mode').read_text()
if mode == 'exit':
    sys.stderr.write('synthetic-private-server-error')
    sys.exit(7)
port = int(args[args.index('-L') + 1].split(':')[1])
with socket.socket() as server:
    server.bind(('127.0.0.1', port))
    server.listen()
    while True:
        client, _ = server.accept()
        with client:
            client.settimeout(1)
            request = bytearray()
            while len(request) < 16:
                chunk = client.recv(16 - len(request))
                if not chunk:
                    break
                request.extend(chunk)
            if request == b'000chost:version':
                client.sendall(b'OK')
                client.sendall(b'AY00040029' if mode == 'ready' else b'AY00040000')
''', 'utf-8')
    arguments = tmp_path / "arguments.json"
    mode = arguments.with_suffix('.mode')
    mode.write_text('ready')
    real_popen = subprocess.Popen
    calls = []
    children = []
    spawned = threading.Event()

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        child = real_popen([sys.executable, str(program), str(arguments), *argv[1:]], **kwargs)
        children.append(child)
        spawned.set()
        return child

    monkeypatch.setattr(adb_server.subprocess, 'Popen', launch)
    cancel = threading.Event()
    owned = adb_server.OwnedAdbServer(tmp_path / 'adb.exe', tmp_path / 'adb-home', 'test-transport-example', cancel)
    yield owned, calls, arguments, mode, spawned
    owned.close()
    leaked = [child for child in children if child.poll() is None]
    for child in leaked:
        child.kill()
        child.wait(timeout=2)
    assert not leaked, 'The manager lost an owned child without reaping it'


def test_concurrent_start_uses_one_owned_loopback_server_and_closes_only_its_child(managed, monkeypatch):
    owned, calls, arguments, _, _ = managed
    monkeypatch.setenv('ADB_SERVER_SOCKET', 'tcp:192.0.2.9:5037')
    monkeypatch.setenv('ANDROID_ADB_SERVER_ADDRESS', '192.0.2.9')
    monkeypatch.setenv('ANDROID_ADB_SERVER_PORT', '5037')
    with ThreadPoolExecutor(max_workers=8) as workers:
        ports = list(workers.map(lambda _: owned.ensure(), range(8)))
    assert len(set(ports)) == 1 and len(calls) == 1
    assert ports[0] != 5037
    argv, options = calls[0]
    assert argv[1:] == ['-L', f'tcp:{ports[0]}', '--one-device', 'test-transport-example', 'server', 'nodaemon']
    assert json.loads(arguments.read_text()) == argv[1:]
    assert options['stdin'] == options['stdout'] == options['stderr'] == subprocess.DEVNULL
    assert all(key not in options['env'] for key in (
        'ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_ADDRESS', 'ANDROID_ADB_SERVER_PORT'))
    assert options['env']['ANDROID_USER_HOME'] == str(owned.directory)
    child = owned._process
    assert child.poll() is None
    owned.close()
    owned.close()
    assert child.poll() is not None and owned._process is None and owned._port is None


def test_dead_owned_server_is_replaced_without_reusing_a_numeric_pid_as_authority(managed):
    owned, calls, _, _, _ = managed
    owned.ensure()
    previous = owned._process
    previous.terminate()
    previous.wait(timeout=2)
    owned.ensure()
    assert owned._process is not previous and len(calls) == 2
    assert owned._process.poll() is None


def test_cancelled_start_never_spawns(managed):
    owned, calls, _, _, _ = managed
    owned.cancel.set()
    with pytest.raises(ClientConnectionError) as error:
        owned.ensure()
    assert error.value.code == 'CLIENT_CANCELLED' and calls == []


def test_cancel_during_readiness_reaps_the_owned_child(managed):
    owned, calls, _, mode, spawned = managed
    mode.write_text('bad-version')
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(owned.ensure)
        assert spawned.wait(timeout=2)
        owned.cancel.set()
        with pytest.raises(ClientConnectionError) as error:
            pending.result(timeout=2)
    assert error.value.code == 'CLIENT_CANCELLED' and len(calls) == 1
    assert owned._process is None


@pytest.mark.parametrize('failure', ['exit', 'bad-version'])
def test_early_exit_or_invalid_protocol_is_not_server_readiness(managed, monkeypatch, failure):
    owned, calls, _, mode, _ = managed
    mode.write_text(failure)
    monkeypatch.setattr(adb_server, 'STARTUP_TIMEOUT', .3)
    with pytest.raises(ClientConnectionError) as error:
        owned.ensure()
    assert error.value.code == 'CLIENT_ADB_SERVER_FAILED'
    assert 'synthetic-private' not in str(error.value)
    assert len(calls) == 1 and owned._process is None and owned._port is None


def test_spawn_failure_has_no_process_or_private_diagnostics(managed, monkeypatch):
    owned, _, _, _, _ = managed

    def fail(*_args, **_kwargs):
        raise OSError('synthetic-private-path')

    monkeypatch.setattr(adb_server.subprocess, 'Popen', fail)
    with pytest.raises(ClientConnectionError) as error:
        owned.ensure()
    assert error.value.code == 'EMULATOR_TOOLS_MISSING'
    assert 'synthetic-private' not in str(error.value) and owned._process is None
