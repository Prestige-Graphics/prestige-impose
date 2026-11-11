# Prestige Impose

A desktop imposition app for print shops: it puts business cards, postcards,
flyers, folded cards and numbered tickets onto a press sheet, ready to send to
a Fiery as a plain job, so nobody needs a Fiery Impose licence. It started as an
in-house tool for the Konica C4070 at Prestige Graphics. Staff use it every day.

The person you're working with is **Leo**, owner of Prestige Graphics (print and
signage, Vaughan ON). He isn't a developer: explain things plainly, show
results instead of describing code, and give a recommendation, not a menu.

## Where it's going (Leo, 2026-10-15)

This moved out of the production agent workspace (`agents/production`) into its
own workspace because Leo is considering **selling it** and adding **booklet
making** (saddle stitch, signatures, creep). Every decision should keep that in
mind. Open questions to settle before building toward a paid product:

- **PyMuPDF is AGPL.** Selling a closed-source app on it needs a commercial
  licence from Artifex, or the app has to be AGPL too, or the PDF engine has to
  change. Price this first; it's the biggest business decision.
- **The GitHub repo is public.** A paid product needs it private, and then the
  self-updater (which downloads public release assets) needs another way to
  fetch updates.
- Code signing (Windows SmartScreen warning, Mac Gatekeeper), licence keys or
  activation, and the Prestige- and Fiery-specific names and defaults.

### The plan (agreed 2026-10-19 to 2026-10-21)

Leo's plan doc: https://claude.ai/code/artifact/1a4b8319-1c42-482d-b8c5-12e34cea3870
(read it with the Claude Docs tools). In short: all new work goes in a
separate "Prestige Impose Next" copy (its own branch, folder, Start menu entry
and settings) plus a CI lock so only `main` can publish. Booklets come first;
the PyMuPDF licence decision runs alongside; making it work for any shop, then
selling, come after. Nothing is built yet: waiting on Leo's go-ahead for the
Next copy.

Additions Leo has decided on (2026-10-21):
- **Yes:** a check before Send to Fiery (one line: sheet, orientation, sheets,
  duplex, press, with a warning when something looks off); a "Report a problem"
  button (useful even if the app stays internal); recent jobs shared across
  staff (still to choose where they're stored: a OneDrive folder, which is
  Claude's suggestion for internal use, or an online database such as Supabase
  if selling comes soon).
- **Later:** filling boxes from a spreadsheet (badges, cards), building on the
  number editor.
- **Unclear:** a printed cutting sheet for the manual guillotine. Leo said
  "we don't have that, keep it for if we sell", possibly thinking of the Duplo
  automatic cutters. Confirm with him.
- **No:** preflight (not useful enough); a sheet-size comparison (the app's
  "Fit most" was removed on purpose, and this would bring it back).
- Not yet in the plan doc: the additions above. Add them when Leo confirms.

## Rules

- **Reads are free. Writes are confirmed.** Releasing, pushing, tagging,
  anything that reaches staff or the public, and anything in OneDrive needs
  Leo's go-ahead. Shipping a release happens when Leo says **"ship"**.
- **Never search, glob, grep or recurse OneDrive.** Walking a OneDrive folder
  downloads everything in it. Ask Leo for exact file paths.
- **No client files in this repo** (it's public). Test with generated PDFs or
  copies in a temp folder outside the repo.
- Commit only when asked. End commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `CHANGELOG.md` is what staff read in the "Update available" window: plain
  words for the person at the press, no jargon, no em dashes.
- Business facts (clients, staff, the press, Fiery) live in Leo's vault at
  `C:\Users\Gallo\Vaults\Prestige-brain` (see `~/.claude/CLAUDE.md`). Use the
  `prestige-brain` skill. Don't put secrets or personal data there.

## Working on it

```
.venv/Scripts/python -m pytest -q        # engine and numbering tests (117 at 1.3.0)
.venv/Scripts/python run_app.py --selftest
```

- Leo's Start menu copy and the PDF right-click menu run **this folder** from
  source (`tools/install_dev_windows.py`), so a change here is live for him on
  the next launch. In Task Manager it shows as **pythonw**, not Prestige Impose.
  Staff run the installed build.
- Before saying something works, run it: tests, the self-test, and for window
  changes, drive the real window (a test script that opens the app, acts, and
  checks the result or a screenshot).
- Python 3.13, Tkinter/ttk, PyMuPDF, PyInstaller, Inno Setup. Windows and Mac.

### Layout

```
prestige_impose/
  engine.py         layout, gutters, marks, scale to fit, numbered plans, rendering (no windows)
  app.py            the main window
  numbering.py      numbered tickets: boxes, fitted backgrounds and borders, drawing numbers
  number_editor.py  the "Place numbers" window (boxes, snap guides, copy/paste, undo)
  renderer.py       page drawing in a helper process so heavy files never freeze the window
  updater.py        update check and self-install from GitHub releases
  fiery.py          Send to Fiery (Held queue)
  selftest.py       run by every build before release
presets/            shared presets shipped with each release (edited from the dev copy only)
packaging/          PyInstaller spec, Inno Setup script
tools/              icon, release notes, dev install, install sheet
.github/workflows/release.yml   tag v* -> test, build Windows + 2 Macs, self-test, publish
```

### Things that bit before

- PyMuPDF must not be used from two threads. Page drawing runs in a separate
  **process** (`renderer.py`, multiprocessing spawn); `run_app.py` calls
  `freeze_support()` for the frozen build. Closing terminates the helper
  without waiting.
- Rotated numbers and their backgrounds: `shape.finish(morph=...)` turns in PDF
  space (y up), so on the page the turn is `Matrix(-rot)`. Backgrounds are
  committed before text so they sit under the numbers.
- In the number editor, `settings()` refits and replaces `self.boxes`: call it
  before taking a reference to a box.

## Releasing (when Leo says "ship")

1. `__version__` in `prestige_impose/__init__.py` and the top `CHANGELOG.md`
   section match, with the date set.
2. Tests and self-test pass. Commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. Wait for the "Build and release" workflow; check the release has 3 assets
   (Windows Setup exe, Mac arm64 zip, Mac x86_64 zip).
4. Replace the installers in `C:\Users\Gallo\OneDrive\Apps\Prestige Impose`
   (exact path, no walking) and run `python tools/make_install_sheet.py X.Y.Z`.
5. Note the release in the vault.

Publishing a release by hand outside CI is not allowed; always go through the tag.

## Open items (as of 2026-10-15)

- **1.3.0 released 2026-10-15** (numbered tickets, cut and stack, helper-process
  renderer, Scale to fit turn fix, close fixes). Installers and install sheet
  are in OneDrive; the vault's `company/equipment.md` has it.
- **Landscape printed portrait.** Leo made a 12x18 landscape sheet with Scale
  to fit and it printed portrait; the file was already landscape, so the 1.3.0
  turn fix may not be the cause. Still need: how he printed it, what the sheet
  looked like, the Held job, the file path.
- **Heavy files.** Leo's 14 MB file that was hard to work with: get its path and
  test 1.3.0 against it.
- **Cut and stack direction.** Needs a real test print to see which way the
  press's output tray stacks; add a "reverse" switch if the order comes out
  backwards.
- **Box padding.** Leo asked for padding to "start at 13pt, 13pt should be 0";
  implemented as 0 = tight around the number. Confirm that's what he meant.
- Old test jobs to delete in the Fiery Held queue: 3342-3344, 3310, 3311, 3316,
  and the collate tests 3884-3886 (2026-11-11). IPP Cancel-Job answers OK but
  leaves held jobs in Held: delete them in Command WorkStation.
