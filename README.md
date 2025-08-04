# dreamSort Mod Manager

![dreamSort Logo by qishiqi, MH4 Guildmarm in a pose inspired by Yoohyeon from Dreamcatcher](./image.png)

## A mod manager designed to simplify the modding experience for Monster Hunter Generations Ultimate (MHGU) on Ryujinx

>Developed by Handburger
>
>Contributors:
>
>jSQrD (jSQrD-dev): Linux Instructions and Support
>
>qishiqi: Application Logo

Supports Windows x64, Linux, Steam Deck

Key Features:

* Install mods easily with drag-drop folders, 7z or zip files (6.2.4 feature).
* Install cheats easily via checkbox and have it be applied to Ryujinx. (bugfixed)
* Clear all loaded mods & cheats via UI buttons.
* Direct Ryujinx integration (you don't have to use the various menus in Ryujinx anymore!)
* Launch GU from dreamSort directly
* Sort mods based on importance or conflicts.
* Renames Mods to align with user-defined sorting.
* Pre-set to Ryujinx MHGU mod folder automatically.
* Colour coded outline based on mod installation compatibility (Green is overrides, Red means conflicts, blue for no conflicts).
* List View and Tree View, with list is where you enable or disable desired mods, and tree view being which files specifically are overriding or conflicting.
* Edit cheats in-app with the editor.
* Right-click to delete any mod or cheat you don't want.
* App warnings if Ryujinx is running before you press apply - avoiding errors.
* Permanent Dark Mode (Hurray!)
* Icon inspired by Yoohyeon from Dreamcatcher.

### Downloads

[Download from Gamebanana](https://gamebanana.com/tools/20124)

### For Compiling

#### Step 1: Install System Packages

You still need to install tkinter from your distribution's package manager, as it's a system dependency and not a Python package that can be installed with pip or uv.

##### For Ubuntu/Debian

```bash
apt-get install python3-tk
```

##### For Fedora

```bash
dnf install python3-tkinter
```

##### For Arch

```bash
pacman -S tk
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
pip install tkinterdnd2 customtkinter pyinstaller pillow
```

##### Using uv

```Bash
uv pip install tkinterdnd2 customtkinter pyinstaller pillow
```

#### Step 4: Compile the Binary

Finally, run the pyinstaller command. Since your venv is active, pyinstaller will use the libraries you just installed.

```Bash
pyinstaller --onefile --windowed --noconfirm --icon="icon.png" --add-data="icon.png:." HB_dreamSort.py
```

This will create a standalone executable in the dist folder of your project directory.

For Windows Python Pyinstaller compilation

```powershell
pyinstaller --onefile --windowed --noconfirm --icon="icon.png" --add-data="icon.png:." HB_dreamSort.py
```
