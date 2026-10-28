SKY PLANE SMP LAUNCHER - how to build it
=========================================
1. Install Python 3.9 or newer from https://www.python.org/downloads/
   (tick "Add python.exe to PATH").
2. Unzip this folder anywhere. Double-click build.bat.
   It installs what it needs and creates:  dist\SkyPlaneSMP.exe
3. Test SkyPlaneSMP.exe yourself first. Log in, press Play, check you land on the server.
4. Send ONLY SkyPlaneSMP.exe to your players.

Where things are stored on a player's PC
   %APPDATA%\SkyPlaneSMP\            (paste this in the Explorer address bar)
       launcher.log   - launcher messages
       game.log       - Minecraft output (send this to me if the game crashes)
       minecraft\     - the game, mods, worlds, settings
It does not touch the player's normal .minecraft folder.

Changing settings
   Open core.py. At the top you can change the server address, mod download link,
   and RAM is picked automatically. Run build.bat again after any change.

Updating the mods later
   Option A: upload the new zip, put the new link in MODS_URL, rebuild, resend the .exe.
   Option B (no rebuild): make a text file containing {"url": "NEW ZIP LINK"},
   host it at a link that always stays the same (a GitHub file or gist), and put that
   link in MANIFEST_URL. The launcher then picks up new mods by itself.

Notes
   - Windows may show "unknown publisher" the first time. Click More info > Run anyway.
     This is normal for programs that are not code-signed.
   - Microsoft login uses PortableMC's own app ID (AZURE_APP_ID in core.py). It works for
     a private group of friends. If Microsoft ever blocks it, you would need to register
     your own app.
