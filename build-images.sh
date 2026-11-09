#!/bin/bash

#
# Copyright (C) 2023 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

# Terminate on error
set -e

# Prepare variables for later use
images=()
# The image will be pushed to GitHub container registry
repobase="${REPOBASE:-ghcr.io/platypuschan}"
# Keep the published image name aligned with module-info.yml, which derives
# "adguard-home" from the repository name "ns8-adguard-home".
reponame="adguard-home"
repository_source="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-Platypuschan/ns8-adguard-home}"
# Official AdGuard Home release image, pinned by digest. NS8 passes it to
# the module as ADGUARDHOME_IMAGE. pypkg/AdGuardHome.template.yaml comes from
# the setup wizard of this release; check it when updating.
adguard_image="docker.io/adguard/adguardhome:v0.107.79@sha256:aba9e3bf0613be3ba3755e1fc311b126e2c24bec25e18b6483894a88283074f0"
# Both release packaging and CI compile the exact same UI stage.
# Keep this explicit image pin synchronized with ui/Containerfile (regression-tested).
NODE_IMAGE="docker.io/library/node:24.22.2-bookworm"
ui_builder="localhost/adguard-ui-${GITHUB_SHA:-$(git rev-parse --short HEAD)}"
buildah bud --target ui -t "${ui_builder}" -f ui/Containerfile ui
ui_container=$(buildah from "${ui_builder}")
container=$(buildah from scratch)
trap 'buildah rm "${ui_container}" "${container}" >/dev/null' EXIT
rm -rf ui/dist
mkdir -p ui/dist
ui_mount=$(buildah mount "${ui_container}")
cp -a "${ui_mount}/app/dist/." ui/dist/
buildah unmount "${ui_container}"

# Add imageroot directory to the container image
buildah add "${container}" imageroot /imageroot
buildah add "${container}" ui/dist /ui
# One rootless instance per node: it binds port 53 on the host network.
# node:fwadm opens port 53 in the firewall; one reserved port for the web UI.
# IMAGETAG overrides the published module tag (latest by default).
buildah config --entrypoint=/ \
	--label="org.opencontainers.image.source=${repository_source}" \
	--label="org.opencontainers.image.revision=${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}" \
	--label="org.nethserver.authorizations=traefik@node:routeadm node:fwadm" \
	--label="org.nethserver.tcp-ports-demand=1" \
	--label="org.nethserver.rootfull=0" \
	--label="org.nethserver.min-core=3.23.0" \
	--label="org.nethserver.max-per-node=1" \
	--label="org.nethserver.images=${adguard_image}" \
	"${container}"
# Commit the image
buildah commit "${container}" "${repobase}/${reponame}"

# Append the image URL to the images array
images+=("${repobase}/${reponame}")

#
# Setup CI when pushing to Github.
# Warning! docker::// protocol expects lowercase letters (,,)
if [[ -n "${CI}" ]]; then
	# Set output value for Github Actions
	printf "images=%s\n" "${images[*],,}" >>"${GITHUB_OUTPUT}"
else
	# Just print info for manual push
	printf "Publish the images with:\n\n"
	for image in "${images[@],,}"; do printf "  buildah push %s docker://%s:%s\n" "${image}" "${image}" "${IMAGETAG:-latest}"; done
	printf "\n"
fi
