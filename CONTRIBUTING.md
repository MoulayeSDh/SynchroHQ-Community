# Contributing to SynchroHQ Community

Thank you for your interest in SynchroHQ Community. The repository is public;
the dependency, attribution, and commercial licensing reviews continue. Please
follow the process below when proposing a change.

## Before you contribute

- Use Discussions for questions and proposals; use Issues for reproducible bugs.
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
- For a substantial change, describe the intended behavior before writing code.
- Submit focused pull requests with a description of the change and how it was
  checked. Do not include customer data, credentials, or Enterprise source.
- Confirm that you have the right to contribute every file you submit, including
  generated assets and material derived from third parties. Preserve upstream
  copyright and license notices.

## Development checks

The development setup is in [README.md](README.md). Before submitting a code
change, run the relevant backend or frontend checks from
`.github/workflows/quality.yml`. Deployment changes should also pass the
appropriate Compose configuration and production preflight checks.

## Licensing of contributions

First-party Community code is licensed under `AGPL-3.0-only`. A contribution
intended for this repository must be compatible with that license. A pull
request alone does not grant D-Corp Invest additional rights to license the
contribution commercially. Maintainers review the provenance and licensing of
each contribution before merging. If a change is also intended for a separately
licensed commercial offering, the maintainer must obtain any additional rights
through an explicit agreement with the contributor. No contributor agreement
is implied by opening a pull request.
