"""Assemble captured app-tab screenshots into one dated PDF.

Usage:
    python3 analysis/app_screens_pdf.py --shots-dir DIR --out-dir DIR [--date YYYY-MM-DD] [--out-name NAME]

Screenshots are grouped into three top-level sections by file-name prefix:
    01-breakouts*   -> "Breakouts"
    02- .. 13-*     -> "Patterns" (sub-headings from SLUG_MAP)
    14-*            -> "Chart Patterns"
Each screenshot gets its own A4 portrait page, scaled to the page width.
Screenshots are only read; nothing is written except the PDF.
"""
import argparse
import datetime as _dt
import os
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

MARGIN = 10 * 2.834645669  # 10 mm in points
HEADER_H = 14              # points reserved at the top for the page header
SUBHEAD_H = 22             # points reserved for the sub-heading line
MAX_OUTPUT_MB = 20.0
DOWNSCALE_WIDTH_PX = 1200

SECTION_BREAKOUTS = "Breakouts"
SECTION_PATTERNS = "Patterns"
SECTION_CHART = "Chart Patterns"

# Exact mapping: file-name slug (name without the "-<letter>.png" suffix) -> (section, sub-heading).
SLUG_MAP = {
    "01-breakouts": (SECTION_BREAKOUTS, "Breakouts"),
    "02-patterns-top": (SECTION_PATTERNS, "Market Behaviour and top of Patterns"),
    "03-patterns-long-side": (SECTION_PATTERNS, "Long-Side (Bullish)"),
    "04-patterns-short-side": (SECTION_PATTERNS, "Short-Side (Bearish)"),
    "05-patterns-structural": (SECTION_PATTERNS, "Structural Patterns"),
    "06-patterns-volatility-default": (SECTION_PATTERNS, "Volatility Intelligence"),
    "07-vol-early-warning": (SECTION_PATTERNS, "Volatility Intelligence > Early Warning"),
    "08-vol-bullish-expansion": (SECTION_PATTERNS, "Volatility Intelligence > Bullish Expansion"),
    "09-vol-bearish-expansion": (SECTION_PATTERNS, "Volatility Intelligence > Bearish Expansion"),
    "10-vol-wyckoff-x-volatility": (SECTION_PATTERNS, "Volatility Intelligence > Wyckoff x Volatility"),
    "11-vol-alerts": (SECTION_PATTERNS, "Volatility Intelligence > Alerts"),
    "12-vol-historical-validation": (SECTION_PATTERNS, "Volatility Intelligence > Historical Validation"),
    "13-patterns-wyckoff-2": (SECTION_PATTERNS, "Wyckoff Institutional Accumulation (2.0)"),
    "14-chart-patterns": (SECTION_CHART, "Chart Patterns"),
}

SECTION_ORDER = [SECTION_BREAKOUTS, SECTION_PATTERNS, SECTION_CHART]
_NAME_RE = re.compile(r"^(\d{2})-(.+?)(?:-[a-z])?\.png$", re.IGNORECASE)


def slug_of(filename):
    """'03-patterns-long-side-a.png' -> '03-patterns-long-side'."""
    base = os.path.basename(filename)
    m = _NAME_RE.match(base)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def classify(filename):
    """Return (section, sub_heading) for a screenshot file name.

    Unknown slugs fall back to the section implied by their number and a
    humanised slug, and are flagged by the caller via classify_strict.
    """
    slug = slug_of(filename)
    if slug in SLUG_MAP:
        return SLUG_MAP[slug]
    num = int(slug[:2]) if slug else -1
    if num == 1:
        return SECTION_BREAKOUTS, (slug or filename)
    if 2 <= num <= 13:
        return SECTION_PATTERNS, (slug[3:].replace("-", " ").title() if slug else filename)
    if num == 14:
        return SECTION_CHART, "Chart Patterns"
    return None, filename


def build_plan(shots_dir):
    """Return ordered list of (filename, section, sub_heading) and a list of unplaced names."""
    names = sorted(n for n in os.listdir(shots_dir) if n.lower().endswith(".png"))
    plan, unplaced = [], []
    for n in names:
        section, sub = classify(n)
        if section is None:
            unplaced.append(n)
            continue
        plan.append((n, section, sub))
    # Stable grouping: section order first, then file-name order within a section.
    plan.sort(key=lambda t: (SECTION_ORDER.index(t[1]), t[0]))
    return plan, unplaced


def contents_mapping(plan):
    """Ordered [(section, [sub_heading, ...])] for the contents list."""
    out = []
    for section in SECTION_ORDER:
        subs = []
        for _, sec, sub in plan:
            if sec == section and sub not in subs:
                subs.append(sub)
        if subs:
            out.append((section, subs))
    return out


def _downscaled_png(path, width_px, scratch_dir):
    from PIL import Image  # only needed for the size-reduction fallback
    img = Image.open(path)
    if img.width <= width_px:
        return path
    h = round(img.height * width_px / img.width)
    img = img.convert("RGB").resize((width_px, h), Image.LANCZOS)
    out = os.path.join(scratch_dir, os.path.basename(path))
    img.save(out, "PNG", optimize=True)
    return out


def render(plan, out_path, date_str, captured_line, generated_at, shots_dir, downscale_px=None, scratch_dir=None):
    page_w, page_h = A4
    c = canvas.Canvas(out_path, pagesize=A4, pageCompression=1)
    c.setTitle(f"PSX Intelligence Daily Patterns Report {date_str}")
    c.setAuthor("PSX Intelligence")

    def header():
        c.setFont("Helvetica", 8)
        c.setFillGray(0.35)
        c.drawString(MARGIN, page_h - MARGIN, f"PSX Intelligence — Daily Patterns Report — {date_str}")
        c.drawRightString(page_w - MARGIN, page_h - MARGIN, captured_line)
        c.setFillGray(0)

    # Cover page
    header()
    c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN * 2, page_h - 90, f"PSX Intelligence — Daily Patterns Report")
    c.setFont("Helvetica", 14)
    c.drawString(MARGIN * 2, page_h - 116, f"Date: {date_str}")
    c.setFont("Helvetica", 10)
    c.drawString(MARGIN * 2, page_h - 136, captured_line)
    c.drawString(MARGIN * 2, page_h - 152, f"Generated {generated_at}")
    c.drawString(MARGIN * 2, page_h - 168, f"{len(plan)} screenshots")

    y = page_h - 210
    c.setFont("Helvetica-Bold", 14)
    c.drawString(MARGIN * 2, y, "Contents")
    y -= 22
    # Page numbers: cover is page 1, screenshot i is page i + 2.
    page_of = {name: idx + 2 for idx, (name, _, _) in enumerate(plan)}
    current_section = None
    for name, section, sub in plan:
        if section != current_section:
            current_section = section
            if y < MARGIN * 4:
                c.showPage(); header(); y = page_h - 90
            c.setFont("Helvetica-Bold", 11)
            c.drawString(MARGIN * 2, y, section)
            y -= 16
        if y < MARGIN * 4:
            c.showPage(); header(); y = page_h - 90
        c.setFont("Helvetica", 9)
        label = f"{sub}"
        c.drawString(MARGIN * 3, y, label)
        c.drawRightString(page_w - MARGIN * 2, y, f"p. {page_of[name]}")
        y -= 13
    c.showPage()

    # One screenshot per page.
    max_w = page_w - 2 * MARGIN
    max_h = page_h - 2 * MARGIN - HEADER_H - SUBHEAD_H
    placed, skipped = 0, []
    for name, section, sub in plan:
        src = os.path.join(shots_dir, name)
        if downscale_px and scratch_dir:
            src = _downscaled_png(src, downscale_px, scratch_dir)
        try:
            img = ImageReader(src)
            iw, ih = img.getSize()
        except Exception as exc:  # unreadable file: report, don't abort the report
            skipped.append((name, str(exc)))
            continue
        header()
        c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGIN, page_h - MARGIN - HEADER_H - 6, f"{section} > {sub}" if section != sub else sub)
        scale = min(max_w / iw, max_h / ih)
        w, h = iw * scale, ih * scale
        x = (page_w - w) / 2
        y = page_h - MARGIN - HEADER_H - SUBHEAD_H - h
        c.drawImage(img, x, y, width=w, height=h, preserveAspectRatio=True, mask=None)
        c.showPage()
        placed += 1
    pages = c.getPageNumber() - 1  # pages already closed with showPage()
    c.save()
    return placed, skipped, pages


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--date", default=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"),
                    help="report/capture date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--out-name", default=None, help="output file name (default PSX_Daily_Report_<date>_screens.pdf)")
    args = ap.parse_args(argv)

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        ap.error("--date must be YYYY-MM-DD")
    if not os.path.isdir(args.shots_dir):
        ap.error(f"--shots-dir not found: {args.shots_dir}")
    os.makedirs(args.out_dir, exist_ok=True)

    plan, unplaced = build_plan(args.shots_dir)
    if not plan:
        print("No PNG screenshots placed; nothing to build.", file=sys.stderr)
        return 1

    out_name = args.out_name or f"PSX_Daily_Report_{args.date}_screens.pdf"
    out_path = os.path.join(args.out_dir, out_name)
    generated_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    captured_line = f"Captured from the live app on {args.date}"

    placed, skipped, pages = render(plan, out_path, args.date, captured_line, generated_at, args.shots_dir)
    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    downscaled = False

    if size_mb > MAX_OUTPUT_MB:
        import tempfile
        with tempfile.TemporaryDirectory() as scratch:
            placed, skipped, pages = render(plan, out_path, args.date, captured_line, generated_at,
                                            args.shots_dir, downscale_px=DOWNSCALE_WIDTH_PX, scratch_dir=scratch)
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        downscaled = True

    print(f"Screenshots placed: {placed} of {len(plan)} found")
    print(f"Pages: {pages}")
    print(f"Output: {out_path}")
    print(f"Size: {os.path.getsize(out_path) / 1024:.0f} KB")
    if downscaled:
        print(f"Note: first build exceeded {MAX_OUTPUT_MB:.0f} MB; rebuilt with PNGs downscaled to {DOWNSCALE_WIDTH_PX} px width.")
    for n in unplaced:
        print(f"Not placed (unrecognised name): {n}")
    for n, err in skipped:
        print(f"Not placed (unreadable): {n}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
