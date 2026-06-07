# Contributing to Video Dialogue HUD

Thank you for considering a contribution! This document explains how to get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Development Setup](#development-setup)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Coding Style](#coding-style)

---

## Code of Conduct

Be respectful. Harassment or abusive language in any form will not be tolerated.

---

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.yml) template. Please include:

- Your OS version and Python version
- Whether you have a CUDA GPU and which PyTorch build you installed
- The exact error message and full traceback
- Minimal steps to reproduce

---

## Suggesting Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.yml) template. Describe the problem you are trying to solve rather than jumping straight to the proposed solution.

---

## Development Setup

```bash
git clone https://github.com/hugo562-a11y/video-dialogue-hud.git
cd video-dialogue-hud

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
pip install pytest          # test runner
```

Run the test suite before making any changes to establish a baseline:

```bash
python -m pytest tests/ -v
```

All tests must pass before you open a pull request.

---

## Submitting a Pull Request

1. **Fork** the repository and create your branch from `master`:
   ```bash
   git checkout -b fix/my-bug-fix
   ```

2. **Make your changes.** Keep each commit focused on a single concern.

3. **Add or update tests** for any logic you change inside `core/`.

4. **Run the full test suite** and ensure it is green:
   ```bash
   python -m pytest tests/ -v
   ```

5. **Open a pull request** against `master`. Fill in the PR template, link any related issues, and describe what you changed and why.

---

## Coding Style

- Follow [PEP 8](https://peps.python.org/pep-0008/). A maximum line length of 100 characters is acceptable for this project.
- Write docstrings for public functions in `core/` — a one-line summary is enough.
- UI code lives in `ui/`; business logic lives in `core/`. Please keep them separate.
- Do not commit debug `print()` statements.
- Comments should explain *why*, not *what*.
