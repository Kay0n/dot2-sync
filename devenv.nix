{ pkgs, ... }:

{
  languages.python = {
    enable = true;
    package = pkgs.python3.withPackages (ps: [
      ps.aiohttp       # dot2 websocket client
      ps.python-rtmidi # Platform M+ MIDI (imported as `rtmidi`)
    ]);
  };

  scripts.dot2-sync.exec = "python main.py";
}
