# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed
- cuDNN sub-library version mismatch when `nvidia-cudnn-cu12` is installed alongside a `cu130` PyTorch build — the `nvidia/cudnn/bin` directory is now excluded from the PATH patch in `main.py`.

---

## [1.0.0] — 2026-05-20

### Added
- Initial public release.
- YOLOv8 Nano person detection and multi-frame tracking.
- Dialogue script import from CSV and Excel (`.xlsx` / `.xls`).
- Faster-Whisper auto-transcription with selectable model sizes (base / small / medium / large-v3).
- Five speech-bubble styles: classic, oval, capsule, tech, sharp.
- Six bubble colours with automatic foreground contrast.
- Four bubble positions (top / bottom / left / right) with collision detection.
- Drag-to-reposition bubble offset on the preview canvas.
- Interactive waveform editor with dialogue-range selection.
- Sentence-level editing: split, merge, delete, restore.
- Bulk speaker rename.
- Undo / Redo for all edit operations.
- Smart export: silence-segment cutting, ffmpeg audio merge, safe CJK path handling.
- PyInstaller spec and `build_portable.bat` for standalone Windows EXE.
- Inno Setup script for Windows installer.
- Unit tests for core data-processing, editing, and rendering logic.

[Unreleased]: https://github.com/hugo562-a11y/video-dialogue-hud/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/hugo562-a11y/video-dialogue-hud/releases/tag/v1.0.0
