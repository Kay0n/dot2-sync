# Builds dist\<name>\ (run <name>.exe inside it) and zips it to dist\<name>.zip, <name> being the project name in pyproject.toml.
# Run on Windows from the project folder, with the app closed so its files can be replaced
. .\venv.ps1 pyinstaller
$name = $project.name

& $python -m PyInstaller --noconfirm --onedir --windowed --name $name --add-data "pyproject.toml:." src\main.py
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Compress-Archive -Path "dist\$name" -DestinationPath "dist\$name.zip" -Force
