# dreamSort — Quick Tutorial

A short walkthrough for first-time users. For install/build details and the full feature list, see [README.md](./README.md).

**The whole app in one line:** pick your mode → point it at the right folder → **Scan** → tick and reorder mods → **Apply Changes**.

---

## 1. Start it

- **Downloaded release:** run the `dreamSort` executable.
- **From source:** `pip install -r requirements.txt`, then `python dreamSort.py` (or `python -m dreamsort`).
- Installing **`.7z`** archives needs `py7zr`, which the requirements file already includes. Without it, `.7z` imports are refused with a message; `.zip` and folders always work.

## 2. First launch: choose the setup you manage

A dialog asks **"Which setup are you managing?"**:

| Option | Pick it when |
| --- | --- |
| Ryujinx (Switch emulator) | Your mods live under `Ryujinx\mods\contents\` |
| Eden (installed or portable) | Your mods live under `eden\load\` or `eden\user\load\` |
| Morerokk's MHGU Recomp (native PC port) | You run `mhgurecomp.exe` and mods live in its `mods\` folder |

Tick **"Remember this choice on next launch"** if you only use one. Change it later with **File → Switch Mode…**. Each mode keeps its own folder and settings in `config.json`.

## 3. Point it at the folder

Use the **📁** button, or **Auto-Find**. Auto-Find looks for the Ryujinx mods folder, the Eden `load` folder, or `mhgurecomp.exe` depending on the mode you picked. Both paths scan straight away.

| Mode | Folder to select |
| --- | --- |
| Ryujinx | `...\Ryujinx\mods\contents\0100770008DD8000` |
| Eden (installed) | `%APPDATA%\eden\load\0100770008DD8000` |
| Eden (portable) | `<your eden folder>\user\load\0100770008DD8000` |
| Recomp | The folder containing `mhgurecomp.exe` |

Selecting `mods`, `contents` or `load` instead of the title-id folder is the most common mistake. The amber banner under the path box then spells out the folder it expects — read it and fix the path.

Then press **Scan**. **Open** opens that folder in Explorer/Finder so you can see what it found.

## 4. The everyday loop

1. **Tick a row** to enable or disable a mod. Unticked rows stay on disk, just parked once you Apply (a `~` prefix on Ryujinx, a `disabled_mods\` folder on Eden, an `# off:` line in `load_order.txt` on Recomp).
2. **Drag rows** to set priority. The first row loads first; when two mods ship the same file, the app shows which one wins for your mode.
3. **Apply Changes.** Nothing is written to disk before this step — the UI only holds your intent. As soon as anything differs from disk (a tick, a drag, a cheat, a loaded profile) the button turns orange and the status bar says so.

**Disable Mods** and **Disable Cheats** untick everything in one click (they never delete files), and they still need Apply. **Ctrl+click** several rows, then right-click, for Enable/Disable/Delete Selected, Move to top/bottom, or Open mod folder.

Applying does the real work:

- **Ryujinx:** renames folders to match enabled state, writes `games\<title-id>\mods.json`, and rewrites `cheats\enabled.txt`.
- **Eden:** adds/removes the `NN_` load-order prefix and moves parked entries into `disabled_mods\` / `disabled_cheats\`. Eden ignores anything one level deeper, so parked mods stop loading.
- **Recomp:** rewrites `mods\load_order.txt` in the format the recomp's own Mods tab uses; nothing is renamed.

If mods share files, Apply first asks for confirmation and lists the winners. **Close the emulator / recomp before applying** — Windows keeps handles on files a running game is using, and a rename can fail while it is open.

## 5. Installing mods

- **+ Import Mods** → **Archive (zip / 7z)** or **Folder**.
- Or drag archives/folders straight onto the list — the header says *DRAG FILES HERE TO INSTALL*.

Imports are unpacked into the mods folder and the list rescans automatically; a large archive shows a progress overlay. This part is **not** deferred — a drag writes to disk right away, unlike ticks and order which wait for Apply. New mods arrive as normal rows — sort them, adjust ticks, then Apply if you changed anything.

A `.txt` dropped onto the list is treated as a **cheat** rather than a mod (the app asks for a cheat name first), so cheat packs can be dragged in too.

Mods that publish only through **GitHub Releases** (Forge is the usual one) can be tracked too: right-click the row → **Link to GitHub…** → paste `github.com/owner/repo`. The newest release tag is saved into the mod's `.dreamsort.json`, and the row gets the same amber **update** badge once a newer tag is out. **Update from GitHub…** — or the **Updates** list, which shows both sources — downloads the release asset and installs it over the existing folder through the normal staging/rollback path; the asset name that was installed last is preferred, then the shortest archive in the release, and a release carrying no installable archive is listed as *no file* instead of unpacking the repository source. If the repo has no releases, or GitHub's anonymous quota (60 requests/hour per IP, lifted by **File → GitHub token**) is spent, the badge says *check failed* and no download happens; a rate-limited check retries after 15 minutes.

In Ryujinx and Eden modes an install also checks for **trimmed (arcBarber) mods**. Those ship partial `.arc` files — only the entries the mod changed — and only the recomp can merge them, so Ryujinx and Eden would load an archive with most of its files missing. dreamSort compares each incoming `.arc` against the game's own copy in your Recomp folder (`data/romfs`) and, if anything looks partial, shows a **Trimmed Arc Mod** dialog listing the archives and their entry counts before anything is extracted. **Cancel** and either regrow the archives with arcBarber or install the mod in Recomp mode. Keep the Recomp path set even when you manage Ryujinx or Eden — that dump is the only local reference; without it the check falls back to flagging archives with three entries or fewer and says it could not compare.

## 6. Cheats

**Ryujinx mode**

- Each `<build-id>.txt` becomes a group, with one row per `[Name]` block inside it. Ticks are per entry, exactly like Ryujinx's own cheat window.
- Apply writes one `<build-id>-<name> Cheat` line per tick into `<title-id>\cheats\enabled.txt` — that string is the only form Ryujinx matches.
- **Preview enabled.txt** shows what will be written. **+ Import Cheat** pastes a code block and names it. **Disable Cheats** unticks every entry — Apply still has to write the file.

**Eden mode**

- A cheat is a folder, so ticks move folders in and out of `disabled_cheats\`.
- Importing a pack with several `[Name]` blocks splits it into one folder per cheat.
- **Eden Settings** reads Eden's own *enable cheats by default* switch. If it is off, no cheat loads regardless of folder layout; the button offers to turn it on (one key, with a `.dreamsort.bak` copy of the ini beside it).

**Recomp mode:** cheat `.txt` files live in `cheats\`; a `_` prefix means disabled. Patches and plugins get their own tick rows and are moved into `disabled\` when switched off.

## 7. Reading the colours

| Colour | Meaning |
| --- | --- |
| Green | **Wins conflict** — this mod's copy is the one used |
| Red | **Loses conflict** — another mod's copy is used instead |
| Light blue | **Loaded** — enabled, no clash |
| Yellow | **Selected** — currently open in the details pane |
| Grey | **Disabled** — parked, not loaded |

**Tree View** shows the same information grouped per mod with the contested files underneath, which is easier once you have a dozen mods.

## 8. Layout profiles and mod sets

The bottom bar's **Profile ▾** menu holds two different things, both saved in `config.json`:

| Feature | What it remembers |
| --- | --- |
| **Layout profiles** — *Save layout profile…*, *Load layout 'X'*, *Delete layout 'X'*, *Export/Import layout profiles…* | The order and enabled state of your rows. Load one to swap whole setups (e.g. "Vanilla-friendly" vs "Maximum chaos") without redoing the ticks. |
| **Mod sets (matched by md5)…** | Which mod files were installed, identified by the md5 of the file they came from. Applying a set re-ticks its matched mods in their saved order and queues the missing ones for download; the report first shows what matched, what is missing, what changed and what is extra. |

## 9. Launching

**Launch** starts Ryujinx with your game file, the recomp executable, or Eden. Ryujinx and Recomp ask for their exe once (Ryujinx also asks for the `.nsp`/`.xci`) and remember it.

In Eden mode it looks for `eden.exe` a few folders above the mods path, which covers portable installs (`<eden>\user\load\<title-id>`); if it cannot find one it asks once and remembers the path.

## 10. Quick troubleshooting

| Symptom | Fix |
| --- | --- |
| List is empty after Scan | You picked the parent folder. The amber banner says which folder to use — or use **Auto-Find** |
| Ticks and order did nothing in-game | Press **Apply Changes** — nothing is written before that |
| A disabled mod still loads in Ryujinx | Apply again; the `~` folder prefix is what Ryujinx reads |
| Cheats don't load in Eden | Run **Eden Settings** and accept the fix, then Apply |
| A gold banner names MHGU `1.1.0` or similar | The game is older than `1.4.0`, which the mods and cheats here are written for. Install the 1.4.0 update in the emulator, then rescan. **Help → Check MHGU Version** explains what was read |
| Apply fails on a rename | Close the emulator/recomp and retry |
| Paths show `[Username]` | Intentional redaction for screenshots. Typing `[Username]` back in the box resolves to the real path |
| Settings seem forgotten | They save to `config.json` next to the app or executable; **File → Save Config** forces a write |
