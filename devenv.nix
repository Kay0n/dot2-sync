{ pkgs, ... }:

{
  languages.python = {
    enable = true;
    package = pkgs.python3.withPackages (ps: [
      ps.aiohttp       # dot2 websocket client
      ps.python-rtmidi # Platform M+ MIDI (imported as `rtmidi`)
      ps.pyside6       # tray icon and status window
      ps.qasync        # runs asyncio on the Qt event loop
    ]);
  };

  scripts.dot2-sync.exec = "python src/main.py \"$@\"";
}
