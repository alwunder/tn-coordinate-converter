# Contributing

Thank you for helping improve Tennessee Coordinate Converter.

## Development setup

Create a virtual environment and install the project in editable mode:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,map]"
```

Run the checks before opening a pull request:

```powershell
python -m pytest
python -m ruff check .
```

## Pull requests

- Keep each change focused and explain the user-visible effect.
- Add or update tests when behavior changes.
- Preserve coordinate-system names, datums, units, and axis order explicitly.
- Include representative input and expected output for conversion fixes.
- Do not commit generated executables, build output, local environments, or
  sensitive data.

For substantial behavior changes, open an issue first so the expected
coordinate behavior and validation data can be agreed upon.

