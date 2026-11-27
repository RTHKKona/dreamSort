# dreamSort Mod Manager

<img src="./icon.png" alt="Definitely-not-Yoohyeon from Dreamcatcher" width="40%"/>

## A mod manager designed to simplify the modding experience for Monster Hunter Generations Ultimate (MHGU) on Ryujinx, Eden (portable & installed), and morerokk's Recompilation.

> Developed by [Handburger](https://github.com/RTHKKona)
> 
> Presented by definitely not Yoohyeon
>
> Current Version: v7.3.4 (PySide6 build)

> Contributors:
> - jSQrD (jSQrD-dev): Linux Instructions and Support
> - qishiqi: Previous Application Logo Artist

Supports
Tested: Windows 11
Untested: Linux Distros, Steam Deck, Mac OS [I don't own any devices with these so they are not the priority for me.]

## Repository Layout

| Path | Contents |
| --- | --- |
| `dreamsort/` | The application package: `analyzers/` (Ryujinx + Recomp); `eden.py` subclasses `RyujinxAnalyzer` and overrides Eden's differences, `storage/` (atomic writes + config), `helpers/`, `ui/` (Qt widgets, theme, dialogs, drag & drop, main window), `workers/` (QThread scan/install/apply). |
| `dreamSort.py` | Entry point. `python dreamSort.py` (or `python -m dreamsort`).

```bash
pip install -r requirements.txt
python dreamSort.py
```

Key Features:

* Permanent Dark Mode UI, now rendered with Qt (PySide6) and not laggy: the window paints on first show, scrolling and drag-reordering stay smooth on large mod folders.
* Install mods easily with drag-drop folders, 7z, zip or rar archives. Conflicting files are resolved by load order, and the winning copy is put in place by a backup-swap commit that rolls back if the move fails; leftover staging folders are swept on the next scan.
* Every install is screened for `.bat`, `.cmd` and `.ps1` files first — folders, zips, 7z/rar archives and GameBanana downloads alike. What the scanner reads decides how loud the warning is: deleting folders, registry / service edits, downloading more code, hidden or encoded commands, elevation, writes outside the mods folder and browser data all get named. Nothing is extracted until the box is ticked and **Install Anyway** is pressed, so a mod cannot run anything just by being unpacked. Archives that carry real executables (`.exe`, `.dll`, `.so`) are still refused outright, before and after extraction.
* Drag-drop checks read the whole tree (scripts, `.arc` headers, pack markers), so they run on a worker behind a busy bar; the window stays usable. Install progress counts the real work — archive entries, copied files, every job in the drop — so a 9000-file pack moves the bar instead of jumping to 100% before anything is written. Leftover staging is swept on a thread, not on the way into the next scan.
* **Refresh** beside **Scan** drops the cached rules, manifests and folder sizes and re-reads the current mode's mods and cheats from disk.
* Trimmed mods are caught before they land on an emulator. A mod processed with **arcBarber** ships *partial* `.arc` files: the same `ARC\0` header as the game's archive with only the entries the mod changed. Only the recomp merges those (partial arc loading, `runtime/arcmerge.c`); Ryujinx and Eden replace the archive outright, so everything left out reads as missing and the game breaks. Ryujinx and Eden installs therefore read every `.arc` in the incoming folder, zip or 7z, compare its entry table against the game's own copy in the Recomp dump (`data/romfs`), and put up a warning naming each archive, its entry count and whether it could be checked — the same test `arc_partial()` runs: shares entries with the original and lacks the rest. With no dump to compare against, only a table of 3 entries or fewer is called out, and the dialog says so. As of 2026-11-19 there is no emulator plugin for partial arcs, hence the warning.
* Install cheats easily via checkbox and have it be applied to Ryujinx and Eden.
* Ryujinx cheat state is per **entry**, matching Ryujinx itself: a cheat mod's panel groups one row per `<16-digit build id>.txt` and then one tick per `[Name]` block in that file. Apply writes one `<build id>-<name> Cheat` line per ticked entry to `<title-id>/cheats/enabled.txt`, which is the only form Ryujinx's `TamperMachine` matches. Files whose name is not a 16-digit build id, files with a malformed `[header]`, and blocks with no instruction lines stay ignored, exactly as `ModLoader` ignores them.
* The **game** version is checked, because the emulator's own build is not what breaks here: mods and cheats in this list are written for MHGU `1.4.0`, and a title still on `1.0.0` silently ignores both. dreamSort reads the game the emulator loads — the `NSO0` `main` build id out of `exefs` (1.4.0 is `FB08F1D20FD1204F`, the same value cheats are keyed by), Eden's plaintext `nand/*/Contents/registered/yuzu_meta/*.cnmt` records, then the `[v65536]`-style title version in update container names — and raises a banner when the install is older than `1.4.0`. Nothing is claimed when the version cannot be read: an extracted base game with an untagged update on top reports `unverified` instead of a false alarm. **Help → Check MHGU Version** shows what was read and where from.
* Three modes, picked on first run or from the mode button: **Ryujinx**, **Eden** and **morerokk's Recomp**. Each mode remembers its own mod folder in `config.json`.
* Eden works for both the installed and the portable build:
  * installed: `AppData/Roaming/eden/load/0100770008DD8000`
  * portable: `<eden folder>/user/load/0100770008DD8000`
  * Eden loads mods as sub-folders of that title folder, and a cheat is its own sub-folder holding `cheats/<build id>.txt`; a pack with several `[Name]` blocks is split into one folder per cheat, and a pack already named after a build id keeps that id.
  * Eden's own switches are a runtime "Cheats" menu (per-cheat, not saved between sessions) and a per-game Add-ons list that stores disabled names in Eden's config. dreamSort instead parks unticked entries in `disabled_cheats/` or `disabled_mods/` on Apply, so the state is plain folders. Eden only looks one level under the title folder, so parked entries are not loaded.
  * One Eden setting can cancel everything anyway: Core `enable_cheats_by_default` (Eden's System tab). dreamSort reads it from `config/qt-config.ini` and the per-game `config/custom/<title id>.ini` override, and when it is off offers to set it back on — one key, after you confirm, with a `.dreamsort.bak` copy beside the file. The **Eden Settings** button re-runs that check; nothing else in Eden's config is read or written.
  * dreamSort can launch Eden: it reuses a saved `eden.exe` path, otherwise looks for one a few folders above the mods path (portable layouts), and only asks you to pick the exe when neither turns one up.
* App warnings if Ryujinx is running before you press apply.
* Link installed mods to their GameBanana page from the right-click menu, check for updates, or paste a GameBanana link in File → Install from GameBanana link to download and install it. The **Updates** button lists every linked mod with both sources' verdicts (new file, new release tag, up to date, check failed) and an **Update** button that installs the file or release it names, so nothing has to be hunted for in a context menu. A page that offers several files asks once which one to install, and the file ids seen at install are kept in `.dreamsort.json` (`gb_known_file_ids`) so a later upload is told apart from the siblings that were already there.
* GameBanana installs are checked before the download starts: Monster Hunter Generations Ultimate only, Mods in **Plugins / Recomp-Plugins / Recomp-Module / Music**, and zip/7z archives whose mod root holds a `manifest.json` or `manifest.txt` (an archive without one is refused, since the name, version and page link come from it). A `.rar` is read only when 7-Zip or unrar is on PATH, so RAR is not one of the promised archive types. A Recomp-only section (Recomp-Plugins, Recomp-Module) asks to switch to MHGU Recomp before anything is downloaded, instead of dropping the mod into the folder of the loader that is currently selected. The 1-click form `drmsrt:https://gamebanana.com/mmdl/<file>,Mod,<mod id>` works, and a file id in the link pins that exact file instead of the newest one.
* Launch the game from dreamSort directly: Ryujinx with your game file, the Recomp executable, or Eden.
* Mods that only ship through **GitHub Releases** (Forge and friends) can be tracked the same way: right-click a mod → **Link to GitHub…**, paste `github.com/owner/repo`, and the newest release's tag is stored in that mod's `.dreamsort.json` next to the GameBanana fields. From then on the row gets the same amber **update** badge when a newer tag appears, `Check GitHub update` refreshes it on demand, and `Update from GitHub…` downloads the release asset and goes through the same staging, commit and rollback path as any other archive — no `manifest.json` is required, since a release zip is whatever the author attached. The asset rule follows the install: the exact name that was installed wins, otherwise the shortest `.zip`/`.7z`/`.rar` asset; a release with no installable archive is reported as `no file` rather than quietly unpacking the repository source. Only linked mods touch the network, and one check per repo per 24h comes out of the anonymous quota (60/hour per IP); **File → GitHub token** stores a read-only token as `github_token` in `config.json` to lift that, and a rate-limited check backs off for 15 minutes instead of pretending to be current. `update_prefs.on_launch` turns the after-scan check off for both sources.
* Renames mods to align with user-defined sorting/priority.
* Known modpacks are flagged. A pack is matched by its packaging, never by the mods it carries: the installed folder is checked for the bundle's own set of component mods and for the pack's HUD `layout_cfg`, which stores its strings as spaced hex pairs, so a plain text search for the pack name finds nothing. The manual-install tutorial and the zip comment identify an archive before it is unpacked. A single component that carries the pack's versioned name (`HD Textures v4`) is a hit on its own; a bare name like `60FPS Patch` still needs the bundle, the HUD brand or the tutorial. A hit puts a banner over the list, an archive about to be installed asks once, and **Apply Changes** and **Launch** ask again — the banner is easy to miss. **details** lists which signals matched and can mute the notice for that folder (`pack_muted` in `config.json`).
* Dependencies resolve by identity, not folder name: `requires` matches the manifest id, the folder it sits in, or a forge `.nro` that ships the library, and `>=*`-style constraints accept any version. A dependency that is installed but whose manifest is missing still counts, and the same resolution feeds the details panel, the status rows and the apply gate.
* Clear all loaded mods & cheats via UI buttons.
* Sort mods based on importance and conflicts.
* Hold `Ctrl` and left-click rows to select multiple mods, then right-click for bulk Enable / Disable / Delete.
* Colour coded outline based on mod installation compatibility
  > Green = Wins conflict,
  > Red = Loses conflict
  > Light Blue = Loaded
  > Teal = Engine module (Recomp only)
  > Yellow = Currently Selected
  > Grey = Disabled
* Ticks, drags and cheat switches only change the intent; **Apply Changes** is what writes to disk, and the button turns orange while something is unapplied.
* Layout profiles save the order and enabled states; **Mod sets (matched by md5)** remember which mod files were installed and compare them against the current folder.

* Right-click to open menu to delete any mod or cheat you don't want.
* Dual List modes - List View and Tree View.
* Edit cheats in-app with the editor in Ryujinx, Eden and Recomp mode.
* Recomp cheats are `.txt` packs in `<recomp folder>/cheats`; unticking one and pressing Apply puts a `_` in front of the file name, which is how the recomp skips a file whole. **Import Cheat** writes a pasted pack straight into that folder, a dropped `.txt` is checked for `[Name]` headers and 8-hex code words before it is saved, and the details pane lists each entry with View Code / Edit. The recomp's own settings menu can also switch single entries off (`cheats/_off.txt`); dreamSort only flips whole files.
* **Forge plugins** (`.nro`) read the same manifest a romFS mod does: the nearest `manifest.*` from the plugin's own folder up to its mod root, stopping at the mod folder. A manifest sitting beside several `.nro` files is read as the folder's, not as each file's. The row shows the manifest version and author next to the file name, and the details pane is one sheet: the release name with a version pill and an Enabled/Disabled chip, a Disable button and a `···` menu (Check update, Copy path, Uninstall), the author and page link, the id and the description, then *Dependencies* (requires/conflicts statuses, load order) and *Installed* (type, file, and the location with copy and Open folder buttons). romFS mods, Ryujinx/Eden mods and engine modules open on the same sheet: the header's state chip and Disable/Enable switch tick the row, conflict rows keep **Make mine win**, cheat rows keep their tick with View Code / Edit, and a tick on a plugin or exefs row marks Apply as unapplied. When a sheet is taller than the details pane the window grows to show its last row, up to the screen's edge.
* **Engine modules** — the recomp's own native extensions — are their own section, chip and colour, never a mod and never a Forge plugin. A module is `engine_modules/<name>/<name>.dll` (`.so` on Linux) and the port loads it only when `engine_modules/enabled.txt` lists that folder, so dreamSort reads the folders that hold a matching binary, marks one with no binary, and writes that list on Apply (an unticked folder becomes a `# off:` line, and nothing is loaded without the file). Modules run with the game's rights and only exist in Recomp mode: Eden and Ryujinx have no equivalent, so nothing here is ever installed there.
* Path redaction: the folder box, details pane and messages show your name as `[Username]` (e.g. `C:/Users/[Username]/AppData/Roaming/Ryujinx/mods/contents`), so screenshots don't leak it. Typing `[Username]` back in the box still resolves to the real folder. Screenshot all you like!
* Icon is an edited image of definitely-not-Yoohyeon from Dreamcatcher. :)

### Modes and Folder Layouts

| Mode | Where mods live | How a disabled entry is stored |
| --- | --- | --- |
| Ryujinx | `Ryujinx/mods/contents/<title-id>` (or a bare `mods/contents`) | `~` prefix on the folder name; cheats are individual `<build id>-<name> Cheat` lines in `<title-id>/cheats/enabled.txt` |
| Eden, installed | `AppData/Roaming/eden/load/0100770008DD8000` | folder moved into `disabled_mods/` or `disabled_cheats/` |
| Eden, portable | `<eden folder>/user/load/0100770008DD8000` | same as Eden installed |
| Morerokk's Recomp | `<recomp folder>/mods` | `load_order.txt`; cheats are `.txt` files one level up in `<recomp folder>/cheats`, disabled by a `_` prefix on the file name |

Enabled Eden mods get a `NN_` prefix so the emulator's alphabetical load order matches the list; the prefix is stripped for display. Eden folders are not touched on disk until Apply, and the Apply step parks a folder instead of deleting anything.

### Downloads

[from GitHub Releases (Windows, MacOS, Linux)](https://github.com/RTHKKona/dreamSort/releases)

[from GitHub Actions (Windows, MacOS, Linux)](https://github.com/RTHKKona/dreamSort/actions/workflows/build.yml)

[from Gamebanana (Windows Only)](https://gamebanana.com/tools/20124)

---

### For Compiling

The UI uses Qt through the PySide6 wheels, so everything comes from pip.

#### Step 1: System Packages (Linux only)

Qt needs a few shared libraries that minimal Linux images leave out. Without libEGL the frozen binary aborts at startup.

##### For Ubuntu/Debian

```bash
apt-get install libegl1 libgl1 libxkbcommon-x11-0 libdbus-1-3 libglib2.0-0 libfontconfig1 libxcb-cursor0
```

##### For Fedora

```bash
dnf install mesa-libEGL libxkbcommon-x11 glib2 fontconfig
```

##### For Arch

```bash
pacman -S mesa xcb-util-cursor
```

#### Step 2: Create and Activate a Virtual Environment

Navigate to your project's directory and create a new virtual environment.

```bash
python3 -m venv venv --system-site-packages
source venv_name/bin/activate
```

You'll know it's activated when your command prompt changes to include the name of the virtual environment.

#### Step 3: Install Python Libraries

With the virtual environment active, install the required Python packages using pip or uv. They will be installed within your virtual environment, leaving your system's global packages untouched.

##### Using pip

```Bash
pip install -r requirements.txt pyinstaller
```

##### Using uv

```Bash
uv pip install -r requirements.txt pyinstaller
```

#### Step 4: Compile the Binary

Finally, run the pyinstaller command. `dreamSort.py` is the entry point; the application
itself lives in the `dreamsort` package.

```Bash
pyinstaller --onefile --windowed --noconfirm --icon="icon.ico" --add-data="icon.ico:." --add-data="icon.png:." dreamSort.py
```

This will create a standalone executable in the dist folder of your project directory.

For Windows Python Pyinstaller compilation

```powershell
pyinstaller --onefile --windowed --noconfirm --icon="icon.ico" --add-data="icon.ico;." --add-data="icon.png;." dreamSort.py
```

`--onefile` unpacks the Qt libraries to a temp folder on every launch, which costs a
second or two of startup time. If startup latency matters more than shipping a single
file, build with `--onedir` instead: the app then starts immediately and `dist/dreamSort/`
is distributed as a folder.

#### Running from source

```bash
python dreamSort.py
# or
python -m dreamsort
# repair a stale drmsrt: handler (also runs without Qt loaded)
python -m dreamsort --register-protocol
```


---

### More Info
#### Adding Manifest Data
To plugin/mod developers: dreamSort accepts a manifest file located in the same directory depth as the romfs folder (i.e /modName/manifest.txt /modName/romfs/...etc). A plugin picks up the manifest at or above its `.nro`, so `/modName/manifest.json` also describes `/modName/romfs/nativeNX/plugins/<name>.nro`, and a `plugin.json` dropped next to a lone `.nro` describes that file. See `manifest_template.txt` and `manifest_template.json` for examples. Supported keys:
```
manifest_version=1
id=author/mod-name
version=1.0.0
name=My Mod
authors=Author
description=lorem ipsum
GameBanana Page=link.com
requires=author/library>=1.3
conflicts=author/other-mod
load_after=
load_before=
```
* `id` is the canonical lowercase `author/mod-name`; never change it between versions. A manifest that writes capitals is lowercased on read instead of being ignored.
* `requires` / `conflicts` are `id` to a version constraint (`>=`, `>`, `<=`, `<`, `==`, `!=`, or `*`), comma-separated in the txt format. A bare version with no operator is a floor (`>=`), so a newer release still satisfies it; an installed mod whose version is unknown (`*` or nothing) is flagged as a warning, not as a mismatch.
* `load_after` / `load_before` are ordering hints used only when both mods are enabled; they do not imply a requirement.

Acceptable formats and naming schemes:
* manifest.json, manifest.txt, mod.txt, info.txt
* mod.json, info.json, plugin.json

The old three-key text manifest still works as-is and only feeds the details panel:
```
mod_name="My Mod"
version="v3.0"
author(s)="Handburger"
```

Key spelling is forgiving: `mod_name` / `Mod Name` / `name`, `author(s)` / `Author(s)` / `authors`, and `GameBanana Page` / `gamebanana_link` all map to the same fields. Straight quotes, curly quotes, or no quotes are accepted, and a UTF-8 BOM is ignored.

Generic JSON names are treated as a dreamSort manifest only when they contain `manifest_version` or `id`.

#### Tech Stack
* Coding Language - Python
* Front-end UI - PySide6 (Qt 6)
* Background work - QThread workers (scan, install, apply)
* Windows Executable Packaging - PyInstaller
* CI/CD - GitHub Actions
* Hotel? Trivago
* Ryze? qeqeq

#### External Sources
* Used AI to help fix the slow old customtkinter UI into PySide6 and advice on how to refactor the huge blob python into something maintainable.
* https://www.instagram.com/p/DeTSAIAgeWT/?img_index=6 for the Yoohyeon source image
* https://cdn11.bigcommerce.com/s-sqin45el/images/stencil/original/products/7972/175812/20240615_150029_025__90588.1718743213.jpg?c=2 for the Yukumo hat source image

### Contribution
Feel free to fork the repo and open a pull request with a clear description of the improvements.
