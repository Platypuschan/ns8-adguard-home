import json
import pathlib
import re
import unittest
import os
import subprocess
import tempfile
import shutil

class RootlessPackagingTests(unittest.TestCase):
    def test_extracts_ui_with_mount_inside_buildah_namespace(self):
        # Tool-boundary fixture: emulate overlay's namespace requirement, not
        # the compiler or a real module image. Hosted packaging covers those.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'bin').mkdir()
            (root / 'mounted/app/dist').mkdir(parents=True)
            (root / 'mounted/app/dist/index.html').write_text('compiled-ui-fixture')
            shutil.copy(ROOT / 'build-images.sh', root / 'build-images.sh')
            shim = root / 'bin/buildah'
            shim.write_text('''#!/bin/bash
set -eu
case "$1" in
  unshare) shift; export UI_TEST_UNSHARED=1; exec "$@" ;;
  mount)
    if [[ "${UI_TEST_UNSHARED:-}" != 1 ]]; then
      echo 'cannot mount overlay outside buildah unshare' >&2; exit 125
    fi
    printf '%s/mounted\\n' "$UI_TEST_ROOT" ;;
  from) printf '%s-container\\n' "$2" ;;
  bud|unmount|rm|config|commit) : ;;
  add)
    if [[ "$3" == ui/dist ]]; then
      test "$(cat ui/dist/index.html)" = compiled-ui-fixture
    fi ;;
  *) exit 99 ;;
esac
''')
            shim.chmod(0o755)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'UI_TEST_ROOT': str(root), 'GITHUB_SHA': 'fixture-sha', 'CI': ''}
            result = subprocess.run(['bash', 'build-images.sh'], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'ui/dist/index.html').read_text(), 'compiled-ui-fixture')

ROOT = pathlib.Path(__file__).resolve().parents[1]

class UiToolchainTests(unittest.TestCase):
    def test_production_and_dev_use_project_yarn_pin(self):
        pkg = json.loads((ROOT / 'ui/package.json').read_text())
        recipe = (ROOT / 'ui/Containerfile').read_text()
        self.assertIn('@yarnpkg/cli-dist@' + pkg['packageManager'].split('@')[1], recipe)
        self.assertIn('AS ui', recipe)
        self.assertIn('yarn install --immutable', (ROOT / 'ui/build.sh').read_text())
        self.assertIn('--target ui', (ROOT / 'build-images.sh').read_text())
        self.assertIn('exec yarn watch', (ROOT / 'ui/container-entrypoint.sh').read_text())
    def test_native_node_pin_matches_ci(self):
        recipe = (ROOT / 'ui/Containerfile').read_text()
        match = re.search(r'FROM node:([0-9.]+)-bookworm', recipe)
        self.assertIsNotNone(match)
        assert match is not None
        version = match[1]
        self.assertIn('NODE_IMAGE="docker.io/library/node:' + version + '-bookworm"', (ROOT / 'build-images.sh').read_text())
        self.assertIn('node-version: "' + version + '"', (ROOT / '.github/workflows/validate.yml').read_text())
    def test_ci_exercises_actual_bundles_with_pinned_host_css(self):
        workflow = (ROOT / '.github/workflows/validate.yml').read_text()
        self.assertIn('core:latest@sha256:', workflow)
        self.assertIn('yarn test:e2e:dev', workflow)
        self.assertIn('yarn test:e2e', workflow)
        self.assertIn('--target ui', workflow)
