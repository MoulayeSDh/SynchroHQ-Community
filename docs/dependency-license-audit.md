# Dependency license audit

This is a preliminary inventory for the versions in `requirements-lock.txt`
and `community/frontend/pnpm-lock.yaml` at the October 2026 publication
review. The [machine-readable inventory](dependency-license-inventory.csv)
records package, version, declared license, source, and whether the metadata
came from PyPI, the npm registry, or an installed npm package. Package
metadata is a lead for review, not a substitute for the actual license text.

| Scope | Versions checked | Metadata result |
| --- | ---: | --- |
| Python lock | 77 | 76 declared a license; `mypy_extensions` did not |
| npm lock | 602 | 602 declared a license; 127 platform variants were checked against npm registry metadata because they were not installed locally |

The lock includes development and platform-specific packages. This inventory
does not say that every listed package is shipped in every image or served to
every browser. The distributed artifact must be inspected separately.

## Items requiring closer review

- Python: `psycopg`, `psycopg-binary`, and `psycopg-pool` declare LGPL-3.0-only;
  `rfc3987` declares GPLv3+; `certifi`, `fqdn`, and `pathspec` declare MPL-2.0.
  Resolve the missing `mypy_extensions` declaration against its source release.
- npm: the Sharp/libvips platform packages declare LGPL-3.0-or-later in
  combination with other licenses; Lightning CSS and `axe-core` declare
  MPL-2.0. `caniuse-lite` declares CC-BY-4.0 for its data. Confirm which files
  reach each production image or browser bundle and preserve their notices.
- Container images: `python:3.14-slim`, `node:24-alpine`, `golang:1.24-bookworm`,
  `debian:bookworm-slim`, and `postgis/postgis:16-3.5-alpine` appear in the
  Dockerfiles or Compose file. Tags are not immutable digests. Inventory the
  actual base-image packages and notices for the built artifacts.
- MinIO: the Dockerfile builds the pinned source revision
  `0d7408fc9969caf07de6a8c3a84f9fbb10a6739e` and copies its license into
  the final image. Check source-availability and attribution obligations when
  distributing this image.
- Assets: the repository contains a README SVG and three frontend SVG marks.
  Confirm their provenance and the rights of any other form content or artwork.
  Preserve the map interface's OpenStreetMap attribution.

Before a versioned release, inspect actual license files, source archives,
container contents, and frontend output. Record any notices that must accompany
redistributed artifacts. The commercial Enterprise combination needs a separate
rights and compatibility review.
