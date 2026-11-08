# Builds dist\dot2-sync\ (run dot2-sync.exe inside it) and zips it to dist\dot2-sync.zip.
# Run on Windows from the project folder, with dot2-sync closed so its files can be replaced
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onedir --windowed --name dot2-sync src\main.py
Compress-Archive -Path dist\dot2-sync -DestinationPath dist\dot2-sync.zip -Force
