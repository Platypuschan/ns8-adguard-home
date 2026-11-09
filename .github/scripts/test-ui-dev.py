#!/usr/bin/env python3
"""Smoke the real devcontainer, with a disposable source mount, as nonroot."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get('UI_DEV_IMAGE', 'localhost/adguard-ui-dev')

def command(*args):
    return subprocess.check_output(args, text=True).strip()

def main():
    command('podman', 'build', '--target', 'dev', '-t', IMAGE, '-f', str(ROOT / 'ui/Containerfile'), str(ROOT / 'ui'))
    scratch = os.environ.get('RUNNER_TEMP', os.environ.get('TMPDIR', str(ROOT.parent)))
    with tempfile.TemporaryDirectory(prefix='adguard-dev-', dir=scratch) as directory:
        source = Path(directory) / 'app'
        shutil.copytree(ROOT / 'ui', source, ignore=shutil.ignore_patterns('node_modules', 'dist', 'dist-dev', 'test-results', '.yarn'))
        args = ['podman', 'run', '--rm', '--userns=keep-id', '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/app/.test-home', '-v', f'{source}:/app:Z']
        print(command(*args, IMAGE, 'build'))
        for mode in ('watch', 'serve'):
            name = 'adguard-dev-smoke-' + uuid.uuid4().hex[:12]
            try:
                if mode == 'watch':
                    command(*args[:2], '--detach', '--name', name, *args[2:], IMAGE, 'watch')
                    for _ in range(120):
                        logs = command('podman', 'logs', name)
                        if 'built in' in logs:
                            break
                        time.sleep(1)
                    else:
                        raise AssertionError('dev watch did not build')
                else:
                    command(*args[:2], '--detach', '--name', name, '-p', '127.0.0.1::8080', '--entrypoint', 'yarn', *args[2:], IMAGE, 'serve', '--host', '0.0.0.0', '--port', '8080', '--strictPort')
                    port = command('podman', 'port', name, '8080/tcp').rsplit(':', 1)[1]
                    for _ in range(60):
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                                assert '/src/main.js' in response.read().decode()
                            break
                        except (OSError, AssertionError):
                            time.sleep(1)
                    else:
                        raise AssertionError('nonroot interactive serve not ready')
                print(f'PASS actual nonroot dev {mode}')
            finally:
                subprocess.run(['podman', 'rm', '--force', name], check=True, stdout=subprocess.DEVNULL)
                assert subprocess.run(['podman', 'container', 'exists', name]).returncode == 1

if __name__ == '__main__':
    main()
