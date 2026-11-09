# Builds dist\<name>\ (run <name>.exe inside it) and zips it to dist\<name>.zip, <name> being the project name in pyproject.toml.
# Run on Windows from the project folder, with the app closed so its files can be replaced
$project = python -c "import json, tomllib; print(json.dumps(tomllib.load(open('pyproject.toml', 'rb'))['project']))" | ConvertFrom-Json
$name = $project.name

python -m pip install @($project.dependencies) pyinstaller
python -m PyInstaller --noconfirm --onedir --windowed --name $name --add-data "pyproject.toml:." src\main.py
Compress-Archive -Path "dist\$name" -DestinationPath "dist\$name.zip" -Force
