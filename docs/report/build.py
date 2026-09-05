"""Render the project report to docs/VayuChakra-Report.pdf.

Run:  python docs/report/build.py

Chromium's print-to-PDF is the renderer rather than a Python PDF library, for one
reason: the report contains five hand-authored SVG diagrams and a dozen tables whose
column widths have to resolve against real text metrics. A layout engine that already
does that correctly is worth more than the dependency it costs, and Playwright is
already in the toolchain for the dashboard screenshots.

@page in the stylesheet sets the sheet size and the gutter. The running footer comes
from footerTemplate below, because Blink does not implement @page margin boxes.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
#: Every print document in this directory, and where it renders to. Both share the
#: build path so a figure or a footer fix cannot land in one and miss the other.
DOCUMENTS = [
    (HERE / "report.html", HERE.parent / "VayuChakra-Report.pdf"),
    (HERE / "briefing.html", HERE.parent / "VayuChakra-Jury-Briefing.pdf"),
]

# The footer is styled inline: Chromium renders these templates in an isolated context
# that inherits nothing from the page, so a class would resolve to no rule at all.
FOOTER = """
<div style="width:100%;font-family:Calibri,sans-serif;font-size:7.5pt;color:#6f7d89;
            padding:0 16mm;display:flex;justify-content:space-between;
            border-top:0.5pt solid #c8d3de;margin:0 0 4mm;padding-top:2mm">
  <span>VayuChakra &nbsp;·&nbsp; Coupled weather and chemistry forecasting, Delhi NCR</span>
  <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
</div>
"""
HEADER = '<div style="display:none"></div>'


def main() -> int:
    missing = [src for src, _ in DOCUMENTS if not src.exists()]
    if missing:
        print(f"missing sources: {missing}", file=sys.stderr)
        return 1

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for src, out in DOCUMENTS:
            page = browser.new_page()
            page.on("pageerror", lambda e, s=src: errors.append(f"{s.name}: {str(e)[:180]}"))
            page.goto(src.as_uri(), wait_until="networkidle", timeout=60000)
            # Fonts are local (Calibri, Times New Roman, Consolas ship with Windows), so
            # there is nothing to download - but the SVGs still need a layout pass.
            page.wait_for_timeout(600)
            page.emulate_media(media="print")
            page.pdf(path=str(out), format="A4", print_background=True,
                     display_header_footer=True,
                     header_template=HEADER, footer_template=FOOTER,
                     margin={"top": "17mm", "bottom": "20mm",
                             "left": "16mm", "right": "16mm"})
            page.close()
            print(f"wrote {out.relative_to(HERE.parent.parent)}  "
                  f"({out.stat().st_size / 1024:.0f} KB)")
        browser.close()

    if errors:
        print("page errors:", errors, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
