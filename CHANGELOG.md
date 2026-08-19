# Changelog

## Unreleased

- Renamed the application to Tennessee Coordinate Converter to reflect
  support for multiple coordinate systems.
- Added standard Python project metadata, automated tests, and GitHub Actions
  validation for the public repository.
- Replaced the retired PyInstaller-specific deployment documentation with the
  Python Deployment Builder assessment and planning workflow.

## Version 1.0 - 2026-07-29

- Added Carter-to-NAD27 and NAD27-to-Carter conversion without an external
  lookup table.
- Added geographic, Tennessee State Plane, and UTM transformations through
  `pyproj`.
- Added single-point and CSV/JSON batch workflows.
- Added the formatted README-based About tab.
- Added the integrated NGMDB MapView window.
- Added repeatable one-folder Windows packaging with separate GUI and CLI
  launchers.
