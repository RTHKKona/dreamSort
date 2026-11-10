# dreamSort Mod Manager

<img src="./icon.png" alt="Definitely-not-Yoohyeon from Dreamcatcher" width="40%"/>

## A mod manager designed to simplify the modding experience for Monster Hunter Generations Ultimate (MHGU) on Ryujinx, Eden (portable & installed), and morerokk's Recompilation.

> Developed by [Handburger](https://github.com/RTHKKona)
> 
> Presented by definitely not Yoohyeon
>
> Current Version: v7.1.0 (PySide6 build)

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
* Install mods easily with drag-drop folders, 7z or zip files (6.2.4 feature).
* Install cheats easily via checkbox and have it be applied to Ryujinx and Eden.
* Ryujinx cheat state is per **entry**, matching Ryujinx itself: a cheat mod's panel groups one row per `<16-digit build id>.txt` and then one tick per `[Name]` block in that file. Apply writes one `<build id>-<name> Cheat` line per ticked entry to `<title-id>/cheats/enabled.txt`, which is the only form Ryujinx's `TamperMachine` matches. Files whose name is not a 16-digit build id, files with a malformed `[header]`, and blocks with no instruction lines stay ignored, exactly as `ModLoader` ignores them.
* Three modes, picked on first run or from the mode button: **Ryujinx**, **Eden** and **morerokk's Recomp**. Each mode remembers its own mod folder in `config.json`.
* Eden works for both the installed and the portable build:
  * installed: `AppData/Roaming/eden/load/0100770008DD8000`
  * portable: `<eden folder>/user/load/0100770008DD8000`
  * Eden loads mods as sub-folders of that title folder, and a cheat is its own sub-folder holding `cheats/<build id>.txt`; a pack with several `[Name]` blocks is split into one folder per cheat, and a pack already named after a build id keeps that id.
  * Eden's own switches are a runtime "Cheats" menu (per-cheat, not saved between sessions) and a per-game Add-ons list that stores disabled names in Eden's config. dreamSort instead parks unticked entries in `disabled_cheats/` or `disabled_mods/` on Apply, so the state is plain folders. Eden only looks one level under the title folder, so parked entries are not loaded.
  * One Eden setting can cancel everything anyway: Core `enable_cheats_by_default` (Eden's System tab). dreamSort reads it from `config/qt-config.ini` and the per-game `config/custom/<title id>.ini` override, and when it is off offers to set it back on — one key, after you confirm, with a `.dreamsort.bak` copy beside the file. The **Eden Settings** button re-runs that check; nothing else in Eden's config is read or written.
  * dreamSort does not launch Eden; open the emulator yourself for now. [Might implement this at another time]
* App warnings if Ryujinx is running before you press apply.
* Launch GU from dreamSort directly.
* Renames mods to align with user-defined sorting/priority.
* Clear all loaded mods & cheats via UI buttons.
* Sort mods based on importance and conflicts.
* Hold `Ctrl` and left-click rows to select multiple mods, then right-click for bulk Enable / Disable / Delete.
* Colour coded outline based on mod installation compatibility
  > Green = No Overrides,
  > Red = Has Conflicts
  > Light Blue = Loaded
  > Yellow = Currently Selected
  > Grey = Disabled

* Right-click to open menu to delete any mod or cheat you don't want.
* Dual List modes - List View and Tree View.
* Edit cheats in-app with the editor in both Ryujinx and Eden mode.
* Path redaction: the folder box, details pane and messages show your name as `[Username]` (e.g. `C:/Users/[Username]/AppData/Roaming/Ryujinx/mods/contents`), so screenshots don't leak it. Typing `[Username]` back in the box still resolves to the real folder. Screenshot all you like!
* Icon is an edited image of definitely-not-Yoohyeon from Dreamcatcher. :)

### Modes and Folder Layouts

| Mode | Where mods live | How a disabled entry is stored |
| --- | --- | --- |
| Ryujinx | `Ryujinx/mods/contents/<title-id>` (or a bare `mods/contents`) | `~` prefix on the folder name; cheats are individual `<build id>-<name> Cheat` lines in `<title-id>/cheats/enabled.txt` |
| Eden, installed | `AppData/Roaming/eden/load/0100770008DD8000` | folder moved into `disabled_mods/` or `disabled_cheats/` |
| Eden, portable | `<eden folder>/user/load/0100770008DD8000` | same as Eden installed |
| Morerokk's Recomp | `<recomp folder>/mods` | `load_order.txt` |

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
```


---

### More Info
#### Adding Manifest Data
To plugin/mod developers: dreamSort accepts a manifest text file located in the same directory depth as the romfs folder (i.e /modName/manifest.txt /modName/romfs/...etc). You can use manifest_template.txt as the example. Inside of this manifest you can write the following information:
```
mod_name= "My Mod"
version= "v3.0"
author(s)= "Handburger"
```
Acceptable formats and naming schemes:
* manifest.txt, mod.txt, info.txt
* mod.json, info.json, plugin.json

You can use " or ' or none at all around your string, but it is good practice to have quotations around your strings :).

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
