"""
Make the one-page "How to install Prestige Impose" PDF that goes in the shared
OneDrive folder next to the installers.

    python tools/make_install_sheet.py 1.0.0 out.pdf
"""

import sys

import pymupdf as fitz

HTML = """
<h1>How to install Prestige Impose</h1>
<p class="sub">Version {v}. Imposition for the C4070: business cards, postcards,
flyers and folded cards onto a press sheet, ready to print to the Fiery.</p>

<h2>1. Pick your file</h2>
<table>
<tr><td><b>Windows PC</b></td><td>PrestigeImpose-Setup-{v}.exe</td></tr>
<tr><td><b>Mac with an Apple chip</b> (M1, M2, M3, M4...)</td><td>PrestigeImpose-{v}-mac-arm64.zip</td></tr>
<tr><td><b>Older Intel Mac</b></td><td>PrestigeImpose-{v}-mac-x86_64.zip</td></tr>
</table>
<p class="note">Not sure which Mac? Apple menu, then About This Mac.
"Chip: Apple M..." means Apple chip. "Processor: Intel" means Intel.</p>

<h2>2. Install</h2>
<p><b>Windows:</b> double-click the Setup file. It installs in a few seconds and
opens Prestige Impose. No password needed.</p>
<p><b>Mac:</b> double-click the zip, drag <b>Prestige Impose</b> into your
<b>Applications</b> folder, then open it from there.</p>

<h2>3. If a warning appears (first time only)</h2>
<p><b>Windows</b> "Windows protected your PC": click <b>More info</b>, then <b>Run anyway</b>.</p>
<p><b>Mac</b> "can't be opened" or "can't verify the developer": click <b>Done</b>, open
<b>System Settings &gt; Privacy &amp; Security</b>, scroll down, click <b>Open Anyway</b>,
then <b>Open</b>.</p>
<p class="note">This only happens on the first install. The app is made in-house, so it
isn't registered with Microsoft or Apple, which is what the warning is about.</p>

<h2>4. Using it</h2>
<p>Open a PDF from the app, or right-click a PDF and choose <b>Open with &gt; Prestige
Impose</b>. Pick a preset or set the layout, then <b>Save imposed PDF</b>. It saves next
to the original and shows you the file. Or click <b>Send to Fiery</b>: pick the press,
quantity, tray and colour, and the job lands in that press's <b>Held</b> queue in Command
WorkStation with copies and duplex already set. Set the paper there, then print. The
original file is never changed.</p>
<p>On Windows, right-click Prestige Impose in the Start menu and choose <b>Pin to
taskbar</b>. On a Mac, right-click it in the Dock and choose <b>Options &gt; Keep in Dock</b>.</p>

<h2>5. Updates</h2>
<p>When there's a new version, a green <b>Update available</b> button appears at the
top of the window. Click it to see what's new, then <b>Update now</b>. It installs
itself and reopens. You don't need to come back to this folder.</p>

<p class="note">Questions: ask Leo.</p>
"""

CSS = """
* { font-family: sans-serif; }
h1 { font-size: 20pt; margin: 0 0 4pt 0; }
h2 { font-size: 12.5pt; margin: 12pt 0 3pt 0; }
p, td { font-size: 10pt; line-height: 1.35; }
p { margin: 0 0 5pt 0; }
td { padding: 2pt 10pt 2pt 0; }
.sub { font-size: 10.5pt; color: #444; }
.note { font-size: 9pt; color: #555; }
"""


def main():
    version, out = sys.argv[1], sys.argv[2]
    story = fitz.Story(html=HTML.format(v=version), user_css=CSS)
    writer = fitz.DocumentWriter(out)
    page = fitz.paper_rect("letter")
    where = page + (54, 54, -54, -54)
    more = True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    pages = fitz.open(out).page_count
    print(f"wrote {out} ({pages} page{'s' if pages > 1 else ''})")


if __name__ == "__main__":
    main()
