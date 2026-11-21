# Runs the app from source, without building. Arguments are passed on, e.g. .\run.ps1 --button-test
# Run on Windows from the project folder
$appArgs = $args
. .\venv.ps1
& $python src\main.py @appArgs
exit $LASTEXITCODE
