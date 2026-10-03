# Open-source publication review

Community is public and first-party code carries an `AGPL-3.0-only` license.
The checks below continue after publication. This document does not alter the
license or third-party rights; unresolved items must be addressed before a
versioned release or customer distribution.

## Rights and licensing

- Verify the rights needed to license first-party source, forms, documentation,
  and visual assets, including any contractor work, before a versioned release.
  The `COPYRIGHT` notice identifies D-Corp Invest and credits Moulaye; this
  review does not assert a transfer of rights.
- Confirm that `AGPL-3.0-only` reflects the rights holder's intended version
  choice. The official license text has been added unchanged; verify the
  accuracy and scope of the `COPYRIGHT` notice before a versioned release.
- Obtain legal review of the commercial Enterprise distribution. The current AI
  image inherits the Community backend image and imports Community Python
  modules directly. Separate repositories and processes do not settle whether
  distributing the combination under proprietary terms is permitted.
- Define the rights needed for future third-party contributions, especially if
  any Community code may be licensed commercially.

## Third-party software and assets

- The locked Python and JavaScript package metadata is listed in the
  [dependency license audit](dependency-license-audit.md) and its CSV inventory.
  Resolve the missing declaration, inspect actual license texts and built
  artifacts, and record notices and distribution obligations.
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

- The reachable Git history was scanned for common credential patterns,
  private IP URLs, personal email addresses, and forbidden paths. No direct
  Enterprise or client paths were found. Gitleaks 8.30.1 also scanned all seven
  reachable commits with no findings. These scans cannot rule out every secret.
  The sole GitHub Actions artifact was an explicitly synthetic recovery backup
  and has been removed.
- Confirm `.env.example` and deployment templates contain examples only; keep
  real production configuration and backups outside Git.
- Private vulnerability reporting is enabled. Periodically verify the public
  reporting flow and update `SECURITY.md` as support policy evolves.
- GitHub secret scanning and push protection are enabled. Recheck alerts and
  branch protection after each change to repository security settings.
- Recheck dependency advisories, licenses, CI, clean installation, and restore
  against the exact commit intended for each versioned release.
- Review repository metadata, GitHub Actions artifacts, and branch protection
  now that the repository is public.
