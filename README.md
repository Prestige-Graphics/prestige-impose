# Prestige Impose

Imposition for the Konica C4070 at Prestige Graphics: put business cards,
postcards, flyers and folded cards onto a press sheet, ready to send to the
Fiery as a plain job. No Fiery Impose licence needed. Windows and Mac.

## Installing (staff)

Download the file for your computer from the
[latest release](https://github.com/Prestige-Graphics/prestige-impose/releases/latest):

| Computer | File |
|---|---|
| Windows | `PrestigeImpose-Setup-<version>.exe` |
| Mac with an Apple chip (M1, M2, M3, M4...) | `PrestigeImpose-<version>-mac-arm64.zip` |
| Older Intel Mac | `PrestigeImpose-<version>-mac-x86_64.zip` |

Not sure which Mac? Apple menu > About This Mac: "Chip: Apple M..." means Apple chip.

**Windows.** Run the Setup file. If a blue "Windows protected your PC" box
appears, click **More info**, then **Run anyway**. That only happens once.
Prestige Impose is then in the Start menu (right-click it to pin it to the
taskbar), and you can right-click any PDF > **Open with > Prestige Impose**.

**Mac.** Double-click the zip, drag **Prestige Impose** into **Applications**,
and open it. If macOS says it can't verify the developer: open **System
Settings > Privacy & Security**, scroll down, click **Open Anyway**. That only
happens once. Right-click any PDF > **Open With > Prestige Impose**.

**Updates.** When a new version is out, a green **Update available** button
appears at the top of the window. Click it to see what's new, then **Update
now**. It installs itself and reopens.

## Using it

1. Open a PDF (or right-click it > Open with).
2. Pick a preset, or set the layout yourself. Every file starts from the
   defaults.
3. **Save imposed PDF**. It's saved next to the original and shown in File
   Explorer / Finder. Print it to the Fiery and set copies, paper and duplex
   there.

The original file is never changed, and artwork isn't resampled or recompressed.

## Developing (Leo's PC)

```
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
python tools/install_dev_windows.py      # Start menu + right-click, running from this folder
python -m pytest -q                      # engine tests
python run_app.py --selftest             # what every build must pass
```

Presets are saved from the development copy into `presets/shared_presets.json`
and ship to staff with the next release. The installed app can't edit them.

### Releasing an update

1. Bump `__version__` in `prestige_impose/__init__.py` (e.g. 1.0.0 -> 1.1.0).
2. Add a section for it at the top of `CHANGELOG.md`. Staff see that text in
   the "What's new" window, so write it for them.
3. Commit, then tag and push: `git tag v1.1.0 && git push origin main v1.1.0`.

GitHub then tests the engine, builds Windows and both Mac versions, self-tests
each build, and publishes the release. Staff see the update the next time they
open the app. To try a build without releasing, run the workflow by hand
(Actions > Build and release > Run workflow) and download the files from that
run's Artifacts.

Not code-signed: each computer approves the app once on first install (see
above). Updates the app installs itself don't need approval again.

## Layout

```
prestige_impose/
  engine.py     imposition: layout, gutters, margin, rendering (no windows)
  app.py        the window
  updater.py    update check and self-install from GitHub releases
  cli.py        command line, used by the production agent
  selftest.py   run by every build before release
  paths.py      where files live (source vs installed app)
presets/shared_presets.json    shared presets, shipped with the app
packaging/                     PyInstaller recipe, Windows installer recipe
tools/                         icon, release notes, dev install
tests/                         engine tests (generated PDFs only, never client files)
```
