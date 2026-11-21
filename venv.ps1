# Creates .venv with Python 3.12 (the newest with prebuilt python-rtmidi wheels for Windows) if it doesn't exist,
# and installs the dependencies from pyproject.toml into it, plus any packages passed as arguments.
# Dot-sourced by run.ps1 and build.ps1, from the project folder. Sets $python and $project
param([string[]]$ExtraPackages = @())

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

$project = & $python -c "import json, tomllib; print(json.dumps(tomllib.load(open('pyproject.toml', 'rb'))['project']))" | ConvertFrom-Json
& $python -m pip install --quiet --disable-pip-version-check @($project.dependencies) @ExtraPackages
if ($LASTEXITCODE) { exit $LASTEXITCODE }
