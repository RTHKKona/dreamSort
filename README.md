# dreamSort Mod Manager

<img src="./icon.png" alt="dreamSort Logo by qishiqi, MH4 Guildmarm in a pose inspired by Yoohyeon from Dreamcatcher" width="30%"/>

## A mod manager designed to simplify the modding experience for Monster Hunter Generations Ultimate (MHGU) on Ryujinx

>Developed by [Handburger](https://github.com/RTHKKona)
>
>Contributors:
> - jSQrD (jSQrD-dev): Linux Instructions and Support
> - qishiqi: Application Logo

Supports Windows x64, Linux, Steam Deck

Key Features:

* Permanent Dark Mode UI
* Install mods easily with drag-drop folders, 7z or zip files (6.2.4 feature).
* Install cheats easily via checkbox and have it be applied to Ryujinx. (bugfixed)
* App warnings if Ryujinx is running before you press apply - avoiding errors.
* Launch GU from dreamSort directly via Ryujinx CLI.
* Renames mods to align with user-defined sorting.
* Clear all loaded mods & cheats via UI buttons.
* Sort mods based on importance and conflicts.
* Colour coded outline based on mod installation compatibility
  > Green = no overrides,
  > Red = has conflicts,
  > Blue = loaded.
* Right-click to delete any mod or cheat you don't want.
* Dual List modes - List View and Tree View.
* Edit cheats in-app with the editor.
* Icon inspired by Yoohyeon from Dreamcatcher.

### Downloads

[from GitHub Releases (Windows, MacOS, Linux)](https://github.com/RTHKKona/dreamSort/releases)

[from GitHub Actions (Windows, MacOS, Linux)](https://github.com/RTHKKona/dreamSort/actions/workflows/build.yml)

[from Gamebanana (Windows Only)](https://gamebanana.com/tools/20124)

---

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
pyinstaller --onefile --windowed --noconfirm --icon="icon.ico" --add-data="icon.ico:." HB_dreamSort.py
```

This will create a standalone executable in the dist folder of your project directory.

For Windows Python Pyinstaller compilation

```powershell
pyinstaller --onefile --windowed --noconfirm --icon="icon.ico" --add-data="icon.ico;." HB_dreamSort.py
```
---

### More Info
#### Tech Stack
* Coding Language - Python
* Front-end UI - CustomTkinter and tkinterdnd2
* Windows Executable Packaging - PyInstaller
* CI/CD - GitHub Actions

### Contribution
Feel free to fork the repo and open a pull request with a clear description of the improvements.
