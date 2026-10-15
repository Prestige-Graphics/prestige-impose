# What's new in Prestige Impose

Each version's notes are what staff see in the app's "Update available"
window. Write them for the person at the press, in plain words.

## 1.3.0 (2026-10-15)

- **Closing always works.** The "Close Prestige Impose?" box always comes up in front, and clicking the window's X a second time closes straight away. Closing no longer waits for a page still being drawn.
- **Big, heavy files stay quick to work with.** Pages are now drawn by a helper running alongside the window, so a heavy file (an Illustrator file with tens of thousands of shapes, big images) no longer freezes the window when you zoom, scroll or change a setting. While a page is being drawn sharp, the preview shows the nearest version it already has (a little soft for a moment) and a small "Drawing..." note. Page thumbnails are drawn the same way. Opening a heavy file is faster too (the check for the file's own crop marks now skips the artwork in the middle of the page), and the pointer shows it's busy while a big file saves.
- **Fixed: Scale to fit on a sheet the other way round.** A portrait page on a 12x18 landscape sheet (or a landscape page on a portrait sheet) stayed upright and small in the middle. With one page per sheet it's now turned 90° to fill the sheet, and the notes say so. Scale to fit also now allows for "Turn 90°" when working out the size.
- **Numbered tickets.** Open a ticket PDF (page 1 the front, page 2 the back), tick "Number the tickets" and click "Place numbers...". On the front of the ticket, drag a box where a number goes, and another on the stub; every box gets the same number. Set the first number and how many, leading zeros (one tick box), text before the number (like "No. "), the font and the colour (red, black or any CMYK). Each box has its own size, alignment and direction (across, or up or down for a stub). Numbers go on the front only and run in order: sheet 1 has the first tickets, sheet 2 the next, and so on. The preview shows the real numbers. Lay the tickets out with the usual Gangup settings (sheet, rows and columns, gutters, crop marks, duplex). Thousands of tickets save in seconds as a small file. Send to Fiery sends the whole run once.
- **Cut and stack.** Order: "Cut and stack" numbers down through the pile instead of across each sheet. With 500 tickets at 14 to a sheet (36 sheets), the first spot on every sheet runs 1 to 36, the second 37 to 72, and so on. After the guillotine each stack is in order, and piling the stacks gives 1 to 500 straight through with no sorting. The summary lists the stacks. When the tickets don't fill the sheets, choose Spare spots: "Leave blank" (the last stack is a few short) or "Number them as extras" (501 to 504 here).
- **A box behind the number.** Give a number box a background colour (white, yellow, black, red or any CMYK) and a border (colour and thickness), with padding around the number. The background hugs each number, or choose "Widest number, all the same" so every ticket's box is the same width.
- **Boxes wrap the number.** A number box is always exactly the size of the longest number in the run, plus its padding and border, so what you see is the room every number takes. It grows or shrinks as you change the size, padding, text before or how many, keeping its aligned end in place (a right-aligned box grows to the left). Padding 0 puts the border right against the number. A box that runs past the edge of the ticket turns orange. "Preview shows: Last number" puts the last ticket's number on the ticket.
- **Faster box editing.** Duplicate a box (Ctrl+D) to get the same size and look beside it, Alt+drag a box to drag out a copy, Ctrl+C, Ctrl+X and Ctrl+V to copy, cut and paste (paste lands under the mouse), Ctrl+Z to undo and Ctrl+Y to redo, arrows to nudge (Shift for bigger steps). Drag a corner of a box to make the number bigger or smaller (the opposite corner stays put). A box you draw makes the number as tall as the box, and takes the look of the box selected before it.
- **Snap guides.** A box you drag snaps to the ticket's centre and cut edges, and to the edges and centres of the other boxes, with a pink guide line showing what it lined up with. Hold Shift to move freely.
- Ticking "Number the tickets" opens Place numbers straight away, and until a number box is placed the preview shows one sheet instead of the whole run of identical blank sheets.

## 1.2.2 (2026-10-05)

- **13x19 jobs print.** The press's 13x19 is really 330 x 483 mm, a hair different from exactly 13" x 19", so jobs sent from Prestige Impose stopped at the press as a custom size. 13x19 sheets are now made at the press's own size. It's still called 13 x 19 everywhere, and layouts look the same. Tested on Press 1, portrait and landscape.
- Landscape duplex is confirmed to arrive as left/right bind.

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
