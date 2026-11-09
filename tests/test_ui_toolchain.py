import json
import pathlib
import re
import unittest

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
