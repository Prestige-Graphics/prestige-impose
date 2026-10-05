# What's new in Prestige Impose

Each version's notes are what staff see in the app's "Update available"
window. Write them for the person at the press, in plain words.

## 1.2.1 (2026-10-05)

- **Pages panel.** Every page of the file shows as a thumbnail down the left. Drag the divider to widen it and the pages flow into 2, 3 or more columns. Click a page to see the sheet it prints on; Ctrl-click or Shift-click selects several (Cmd on a Mac). Drag pages to move them. Right-click, or the Edit menu above the pages: cut, copy, paste (before or after), duplicate, delete, move to start, move to end, reverse order, insert a blank page, a blank page after every page, insert pages from another PDF, save selected pages as a PDF, select all, undo, and back to the original pages. The usual keys work once you've clicked in the panel: Ctrl+X, C, V, D, A, Z and Delete. A page that isn't the size of the rest is outlined in orange with its size. Only the imposed job changes; the original file is never touched.
- **See every sheet.** The preview shows all the sheets, front and back side by side, and scrolls. At Fit one sheet fills the view; zoom out and more fit across, like Fiery. Prev and Next jump from sheet to sheet.
- **Files open in Normal**, and Normal is now one page per sheet, like Fiery. Gangup type, layout style, rows and columns and gutters only show for Gangup.
- **Your own presets.** Everyone can now save and delete presets on their own computer, and they're kept through updates. The presets that come with the app are added once, and any new ones in a future update are added the same way.
- **Crop marks with bleed.** Two new choices, "With bleed (stretch edges)" and "With bleed (enlarge)". Each piece keeps 0.125" of bleed, the pieces sit 0.25" apart and crop marks go outside the layout at every cut line. If the file has its own bleed, that's what's used. If it has none, bleed is made first: "stretch edges" mirrors the outer 0.125" of the design outward and leaves the design itself alone, and "enlarge" makes the whole design slightly bigger, which cuts a little off its edges. Either way the pieces still cut to the file's own size. "Outside only" is unchanged, for white-background files. "Outside + between pieces" is gone.
- **Layout style**, like Fiery Impose: Standard, Head to head or Foot to foot. It replaces the "Head-to-head" tick box, which actually did foot to foot, so old presets that used it now show "Foot to foot" and still lay out the same way. With only one row there's nothing to pair, so it does nothing.
- **180 slot rotation**, like Fiery Impose: None, Front surface, Back surface, or Front and back surface. For example, Back surface turns every piece on the back upside down for top-bound duplex jobs.
- **Turn 90** is a tick box next to Orientation.
- **Same both sides.** Duplex has a new choice, "Same both sides", that prints every page on the front and the back. A one-page file with duplex on does this automatically.
- **Custom sheet size works.** The width and height boxes were hidden. Typing a wide size, like 19 x 13, sets the orientation to Landscape.
- **Duplex shows as left/right bind in Fiery.** Landscape sheets were arriving as top bind.
- **Sheet sizes go to Fiery by name** (13x19, 12x18 and so on) as well as by size, so the press doesn't read the job as a custom size.
- **The imposed file is named after the job name** when you send to Fiery. A job called "v2" saves as "v2 - imposed 12x18 7x3.pdf" and leaves the earlier file alone.
- **Closing asks first** when a file is open, with "Send to Fiery..." right there. While a job is still sending, it waits.
- The Send to Fiery and Update windows open in the middle of Prestige Impose, not the corner of the screen.
- Fixed: a document turned 90 degrees and printed duplex had its backs upside down.
- Fixed: Ctrl+S in the Send to Fiery window saved the file a second time behind it.
- "Fit most" and "Finish Size" are gone. Presets and the crop mark choices do their jobs.

## 1.2.0 (2026-10-03)

- **Send to Fiery.** The new "Send to Fiery..." button sends the imposed job straight to a press's Held queue in Command WorkStation. Pick the press (Press 1 - C4070 or Press 2 - C4070NEW), the paper, the job name, the quantity, the tray and colour or grayscale. Duplex and the sheet size go with it automatically, and the imposed PDF is saved next to the original as well. Nothing prints until someone releases it from Held.
- Quantity is the number of finished pieces: 500 cards at 21 up sends 24 sheets (always rounded up). For files where every piece is different, or normal documents, it's the number of sets.
- Paper weight and type come from Fiery Virtual Printers set up in Command WorkStation. Until those are set up, choose "Set in Command WorkStation" and set the paper in Held.
- Drag a PDF onto the window to open it.
- Shortcuts: Ctrl+O to open, Ctrl+S to save, Page Up and Page Down to move between sheets (Command on a Mac).
- Suggested presets: when a file matches the size a preset was made for, it offers "Use" under the preset list.
- Pieces can be turned 90 degrees, and "Head-to-head" turns every other row upside down for tent cards and folded pieces.
- "Fit most" now pulls the cards together the way the shop does: until only a sliver of each file's own crop marks still shows between them, so they can still be cut by. On an Illustrator card with a wide edge that's -0.63"; on a 4.083" x 2.583" card it's about -0.30". Business cards on 12x18 come out 7 x 3 either way. It also tries the pieces turned and picks whichever fits more. A file without crop marks of its own is pulled in until its cut lines meet.
- Presets saved after Fit most remember "pulled in" rather than a fixed gutter, so they work out the right gutter for each card.
- The summary shows the size each piece finishes at after cutting, so you can see if a gutter pulls in past the cut line.
- Crop marks option: none, outside only, or outside plus small marks between pieces. They show in the preview, and the outside marks are shortened if needed so they never fall off the sheet. Marks between pieces print on the design, so it warns if a file has artwork at its corners.

## 1.1.0 (2026-10-01)

- Zoom the preview: the - and + buttons under the preview, or Ctrl + and Ctrl - (Command on a Mac) to zoom in toward wherever your mouse is. Ctrl 0 or the Fit button goes back to the whole sheet.
- Ctrl + mouse wheel zooms at the pointer too.
- When zoomed in, drag the preview to move around, or use the mouse wheel and scrollbars (hold Shift to scroll sideways).
- The zoom level shows as a percentage of actual size, like Fiery.

## 1.0.0 (2026-10-01)

- First release for Prestige staff, on Windows and Mac.
- Gangup (Repeat or Unique) and Normal layouts on 12x18, 13x19, 11x17, Letter, Legal or a custom sheet.
- Duplex on or off; backs line up behind their fronts.
- Rows and columns, with "Fit most" to find how many fit.
- Gutters in inches, including negative gutters for Illustrator files with bleed and marks built in. Link the two gutters to move them together; Apply All and Reset.
- Shared presets, starting with "Illustrator Business Cards 12x18".
- The 0.1" press margin is left blank, like Fiery.
- Saves next to the original file and shows it in File Explorer or Finder. The original is never changed, and artwork quality is untouched.
- Right-click a PDF and choose Open with > Prestige Impose.
- Tells you when an update is available and installs it for you.
