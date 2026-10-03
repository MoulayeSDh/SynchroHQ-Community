# Open-source release review (private preparation)

Community remains private. First-party code now carries an `AGPL-3.0-only`
license. This document records checks still required before the repository
visibility changes; it does not alter the license or third-party rights.

## Rights and licensing

- The project owner reports a written assignment of the original SynchroHQ
  code to D-Corp Invest. Verify the document's scope against source, forms,
  documentation, visual assets, and any contractor work before publication.
  Git commit authorship alone is not proof of ownership or assignment.
- Confirm that `AGPL-3.0-only` reflects the rights holder's intended version
  choice. The official license text has been added unchanged; verify the
  accuracy and scope of the `COPYRIGHT` notice before publication.
- Obtain legal review of the commercial Enterprise distribution. The current AI
  image inherits the Community backend image and imports Community Python
  modules directly. Separate repositories and processes do not settle whether
  distributing the combination under proprietary terms is permitted.
- Define the rights needed for future third-party contributions, especially if
  any Community code may be licensed commercially.

## Third-party software and assets

- Inventory direct and transitive Python dependencies from
  `requirements-lock.txt` and JavaScript dependencies from
  `community/frontend/pnpm-lock.yaml`, including their exact versions, license
  expressions, notices, and distribution obligations. Resolve unknown entries.
- Review all container images and bundled binaries. The Community MinIO
  Dockerfile builds a pinned MinIO source release and copies its license into
  the image; verify the corresponding source and notice obligations for any
  distributed image. Review PostGIS/PostgreSQL, Node, Python, Debian/Alpine,
  and any transitive components in the final images.
- Verify rights and attribution for SVG artwork, iconography, fonts, form
  content, translations, and map data. Preserve the existing OpenStreetMap
  attribution in the map interface.
- Add `NOTICE` only for third-party notices actually required by the audited
  materials; do not create an empty or inaccurate notice file.

## Security and publication

- Scan the complete new Community Git history and build artifacts for secrets,
  customer data, private URLs, and proprietary files. A working-tree scan alone
  is insufficient.
- Confirm `.env.example` and deployment templates contain examples only; keep
  real production configuration and backups outside Git.
- Configure and test private vulnerability reporting for external users, then
  update `SECURITY.md` with a reliable contact method and supported versions.
- Recheck dependency advisories, licenses, CI, clean installation, and restore
  against the exact commit intended for public release.
- Confirm the repository and any artifacts remain private until the release
  decision, then review GitHub settings and visibility as a separate step.
