# Changelog

All notable changes to `dod` are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the major version is `0`, minor versions may contain breaking changes. The version comes from the git tag (`vX.Y.Z`), see the README.

## [Unreleased]

### Added

- The `dod` command line client for DODP v1 Services: Environments and configuration, explicit Service addresses with a host boundary, Sessions, all 15 operations, Exchanges with always-on masking, conformance tests (`dod test`), content delivery (`dod issue`, `dod download`, `dod return`), local playback (`dod play`) and an optional TUI (`dod tui`).
- GitHub release workflow: pushing a `vX.Y.Z` tag builds the wheel and sdist and publishes them with SHA-256 checksums.
