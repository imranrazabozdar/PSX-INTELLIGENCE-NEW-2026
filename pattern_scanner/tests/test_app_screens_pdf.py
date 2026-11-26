"""Tests for analysis/app_screens_pdf.py: synthetic PNGs in a tmp dir only."""
import importlib.util
import os
import struct
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("app_screens_pdf", os.path.join(ROOT, "analysis", "app_screens_pdf.py"))
asp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(asp)


def _tiny_png(path, w=40, h=60, rgb=(200, 30, 30)):
    """Write a minimal valid RGB PNG using only zlib (no PIL needed)."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def test_pdf_built_from_three_synthetic_pngs():
    with tempfile.TemporaryDirectory() as shots, tempfile.TemporaryDirectory() as out:
        _tiny_png(os.path.join(shots, "01-breakouts-a.png"))
        _tiny_png(os.path.join(shots, "03-patterns-long-side-a.png"))
        _tiny_png(os.path.join(shots, "14-chart-patterns-a.png"))
        rc = asp.main(["--shots-dir", shots, "--out-dir", out, "--date", "2026-11-26"])
        assert rc == 0
        name = "PSX_Daily_Report_2026-11-26_screens.pdf"
        path = os.path.join(out, name)
        assert os.path.exists(path)
        assert "2026-11-26" in os.path.basename(path)
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"


def test_contents_mapping_order_and_labels():
    with tempfile.TemporaryDirectory() as shots:
        # Create in scrambled order; mapping must come out Breakouts -> Patterns -> Chart Patterns.
        for n in ["14-chart-patterns-a.png", "03-patterns-long-side-a.png", "01-breakouts-a.png",
                  "07-vol-early-warning-a.png", "13-patterns-wyckoff-2-a.png"]:
            _tiny_png(os.path.join(shots, n), w=4, h=4)
        plan, unplaced = asp.build_plan(shots)
    assert unplaced == []
    mapping = asp.contents_mapping(plan)
    assert [section for section, _ in mapping] == ["Breakouts", "Patterns", "Chart Patterns"]
    subs = dict(mapping)
    assert subs["Breakouts"] == ["Breakouts"]
    assert subs["Patterns"] == [
        "Long-Side (Bullish)",
        "Volatility Intelligence > Early Warning",
        "Wyckoff Institutional Accumulation (2.0)",
    ]
    assert subs["Chart Patterns"] == ["Chart Patterns"]


def test_unrecognised_name_is_reported_not_placed():
    with tempfile.TemporaryDirectory() as shots:
        _tiny_png(os.path.join(shots, "01-breakouts-a.png"), w=4, h=4)
        _tiny_png(os.path.join(shots, "notes.png"), w=4, h=4)
        plan, unplaced = asp.build_plan(shots)
    assert [p[0] for p in plan] == ["01-breakouts-a.png"]
    assert unplaced == ["notes.png"]
