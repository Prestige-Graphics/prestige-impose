# What's new in Prestige Impose

Each version's notes are what staff see in the app's "Update available"
window. Write them for the person at the press, in plain words.

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
