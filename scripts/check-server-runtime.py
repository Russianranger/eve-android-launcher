#!/usr/bin/env python3
"""Run the mobile supervisor against the actual ARM64 Docker runtime."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time


def docker(*arguments, timeout=600, check=True):
    try:
        return subprocess.run(['docker', *map(str, arguments)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=check)
    except subprocess.CalledProcessError as error:
        # A failed prepare may never start a container whose logs we can fetch.
        # Preserve the command's captured reason instead of only its exit code.
        print((error.stdout or '')[-30000:])
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='eve-android-server:local')
    parser.add_argument('--backend', default='backend')
    parser.add_argument('--output', default='out/server-runtime-check.json')
    args = parser.parse_args()
    backend = pathlib.Path(args.backend).resolve()
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'schemaVersion': 1, 'passed': False, 'qualification': 'native-arm64-linux-docker', 'androidQualified': False, 'checks': []}
    native_probe = '''
const D=require('/opt/evejs/server/node_modules/better-sqlite3');
const db=new D(':memory:');
if(process.arch!=='arm64'||db.prepare('SELECT 42 AS value').get().value!==42)process.exit(1);
db.close();
console.log(JSON.stringify({node:process.version,architecture:process.arch,nativeSqlite:true}));
'''
    container = None
    temporary = None
    state = None
    user = ['--user', str(os.getuid()) + ':' + str(os.getgid())]
    try:
        result = docker('run', '--rm', args.image, 'node', '-e', native_probe)
        report['native'] = json.loads(result.stdout)
        report['checks'].append('ARM64 Node and compiled better-sqlite3 execute natively')
        temporary = tempfile.mkdtemp(prefix='eve-server-smoke-', dir=output.parent)
        state = pathlib.Path(temporary) / 'state'
        (state / 'config').mkdir(parents=True)
        # Published behavior must match the app's /state and config bindings.
        mounts = ['--mount', 'type=bind,src=' + str(backend) + ',dst=/opt/eve-android,readonly',
                  '--mount', 'type=bind,src=' + str(state) + ',dst=/state',
                  '--mount', 'type=bind,src=' + str(state / 'config') + ',dst=/opt/evejs/config']
        command = ['python3', '/opt/eve-android/server_runtime.py']
        result = docker('run', '--rm', *user, *mounts, args.image, *command, 'prepare')
        (output.parent / 'server-prepare-smoke.log').write_text(result.stdout)
        sentinel = state / 'PRESERVATION-SENTINEL'
        sentinel.write_text('existing player data is kept\n')
        before = (state / 'prepared.json').read_bytes()
        docker('run', '--rm', *user, *mounts, args.image, *command, 'prepare')
        assert sentinel.read_text() == 'existing player data is kept\n'
        assert (state / 'prepared.json').read_bytes() == before, 'Repeated prepare replaced its receipt'
        report['checks'].append('Preparation validates seed and keeps existing state on repeat')
        started = time.monotonic()
        container = docker('run', '--detach', *user, *mounts, args.image, *command, 'start').stdout.strip()
        deadline = started + 480
        status = {}
        while time.monotonic() < deadline:
            path = state / 'run/status.json'
            if path.exists():
                status = json.loads(path.read_text())
                if status.get('phase') == 'failed':
                    raise RuntimeError('Supervisor failed: ' + json.dumps(status))
                if status.get('ready') is True and status.get('phase') == 'running':
                    break
            running = docker('inspect', '--format', '{{.State.Running}}', container).stdout.strip()
            if running != 'true':
                raise RuntimeError('Server container exited before readiness: ' + json.dumps(status))
            time.sleep(1)
        else:
            raise TimeoutError('No authenticated service readiness within 480 seconds: ' + json.dumps(status))
        report['readySeconds'] = round(time.monotonic() - started, 2)
        report['readyStatus'] = status
        # Readiness includes live process identities, so the healthcheck must
        # share the supervisor's PID namespace as it does under Android.
        docker('exec', container, *command, 'check')
        report['checks'].append('Rust market health, world handshake and gateway readiness succeed')
        # Let steady-state child checks execute once before testing shutdown.
        time.sleep(16)
        status = json.loads((state / 'run/status.json').read_text())
        assert status.get('phase') == 'running' and status.get('ready') is True
        (state / 'run/stop').touch()
        exit_status = docker('wait', container, timeout=100).stdout.strip()
        assert exit_status == '0', 'Unclean container exit code: ' + exit_status
        final = json.loads((state / 'run/status.json').read_text())
        assert final.get('phase') == 'stopped' and final.get('cleanShutdown') is True, final
        report['shutdownStatus'] = final
        report['checks'].append('Stop sentinel flushes SQLite and cleanly terminates supervised children')
        (output.parent / 'server-start-smoke.log').write_text(docker('logs', container).stdout)
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        if container:
            logs = docker('logs', container, check=False).stdout
            (output.parent / 'server-start-smoke.log').write_text(logs)
            print(logs[-12000:])
        raise
    finally:
        if container:
            docker('rm', '--force', container, check=False)
        if state is not None:
            status_path = state / 'run/status.json'
            if status_path.exists():
                report['lastStatus'] = json.loads(status_path.read_text())
                shutil.copyfile(status_path, output.parent / 'server-status-smoke.json')
            for name in ('server-console.log', 'market-console.log'):
                source = state / 'logs' / name
                if source.exists():
                    shutil.copyfile(source, output.parent / name.replace('.log', '-smoke.log'))
                    if not report['passed']:
                        print(source.read_text(errors='replace')[-12000:])
        output.write_text(json.dumps(report, indent=2) + '\n')
        if temporary is not None:
            shutil.rmtree(temporary)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
