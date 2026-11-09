#!/bin/sh
set -eu
expected="$(node -p 'require("./package.json").packageManager.split("@")[1]')"
[ "$(yarn --version)" = "$expected" ]
yarn install --immutable
yarn lint
yarn test:stack
yarn build
