#!/usr/bin/env python3
"""
Scanner Job Coordinator for RavenScan.
Handles background scan execution, duplex sheet separation, and progress updates.
"""

import os
import glob
import time
import shutil
import tempfile
import threading
import subprocess
from typing import Callable, Optional, Dict, Any, List, Tuple

# The Raven Compact's rear sensor produces corrupted color data when the page
# feeds at the fast speed used below 300 DPI. Always scan at >= 300 and scale
# down afterwards if a lower resolution was requested.
MIN_HW_DPI = 300

from ravenscan.hardware import RavenHardware, ScannerStatus, ColorMode, ScanSource, PaperSize

class ScanOptions:
    def __init__(
        self,
        color_mode: ColorMode = ColorMode.COLOR,
        resolution_dpi: int = 300,
        source: ScanSource = ScanSource.ADF_DUPLEX,
        paper_size: PaperSize = PaperSize.LETTER,
        auto_deskew: bool = True,
        remove_blank_pages: bool = False,
        ocr: bool = True,
        document_name: str = "Scan",
        save_dir: str = "",
        append_date: bool = True,
    ):
        self.color_mode = color_mode
        self.resolution_dpi = resolution_dpi
        self.source = source
        self.paper_size = paper_size
        self.auto_deskew = auto_deskew
        self.remove_blank_pages = remove_blank_pages
        self.ocr = ocr
        self.document_name = document_name
        self.save_dir = save_dir
        self.append_date = append_date


class ScannerController:
    def __init__(self, hardware: RavenHardware):
        self.hardware = hardware
        self.is_busy = False
        self._cancel_requested = False

    def check_connection(self) -> Tuple[ScannerStatus, Dict[str, Any]]:
        return self.hardware.scan_usb_bus()

    def start_scan_async(
        self,
        options: ScanOptions,
        on_status: Callable[[str], None],
        on_page: Callable[[str, str], None],  # (image_path, side)
        on_complete: Callable[[], None],
        on_error: Callable[[str], None],
        simulation: bool = False,
    ):
        """Launches scan job in a background worker thread."""
        if self.is_busy:
            on_error("Scanner is already performing a job.")
            return

        self.is_busy = True
        self._cancel_requested = False

        thread = threading.Thread(
            target=self._scan_worker,
            args=(options, on_status, on_page, on_complete, on_error, simulation),
            daemon=True,
        )
        thread.start()

    def cancel(self):
        self._cancel_requested = True

    def _scan_worker(
        self,
        options: ScanOptions,
        on_status: Callable[[str], None],
        on_page: Callable[[str, str], None],
        on_complete: Callable[[], None],
        on_error: Callable[[str], None],
        simulation: bool,
    ):
        temp_dir = tempfile.mkdtemp(prefix="ravenscan_job_")
        try:
            status, info = self.check_connection()

            # If simulation or if permissions are not yet set up, use test generation
            if simulation or status != ScannerStatus.READY:
                if status == ScannerStatus.PERMISSION_DENIED and not simulation:
                    on_status("USB permissions needed. Running demo scan mode...")
                else:
                    on_status("Running simulation scan...")

                self._run_simulation_scan(options, temp_dir, on_status, on_page)
                on_status("Scan complete.")
                on_complete()
                return

            # Check if SANE scanimage is available and can drive the device
            if not shutil.which("scanimage"):
                on_error(
                    "Scanner hardware was detected, but no SANE scanning backend "
                    "(scanimage) is installed. Install the 'sane' package to scan."
                )
                return

            on_status("Connecting via SANE backend...")
            success = self._run_sane_scan(options, temp_dir, on_status, on_page)
            if success:
                on_status("Scan complete.")
                on_complete()
                return

            # Hardware was detected but the real scan failed. Report this
            # honestly instead of silently generating a placeholder document
            # that looks like a real scan.
            on_error(
                "Scanner hardware was detected, but the scan failed via the SANE "
                "backend. No document was created."
                + (f"\n\nDetails: {self.last_error}" if getattr(self, "last_error", "") else "")
            )

        except Exception as e:
            on_error(str(e))
        finally:
            self.is_busy = False
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_sane_scan(
        self,
        options: ScanOptions,
        temp_dir: str,
        on_status: Callable[[str], None],
        on_page: Callable[[str, str], None],
    ) -> bool:
        """Attempts to scan using SANE scanimage."""
        try:
            mode_str = "Color" if options.color_mode == ColorMode.COLOR else (
                "Gray" if options.color_mode == ColorMode.GRAYSCALE else "Lineart"
            )
            duplex = options.source == ScanSource.ADF_DUPLEX
            source_str = "ADF Duplex" if duplex else "ADF Front"
            hw_dpi = max(options.resolution_dpi, MIN_HW_DPI)
            # scanimage's PNG writer aborts at end-of-batch on this backend,
            # so capture PNM and convert.
            out_pattern = os.path.join(temp_dir, "page_%03d.pnm")

            cmd = [
                "scanimage",
                "-d", "avision",
                "--mode", mode_str,
                "--resolution", str(hw_dpi),
                "--source", source_str,
                "-x", "216", "-y", "355",   # full legal; ADF stops at paper end
                "--batch=" + out_pattern,
                "--format=pnm",
            ]

            on_status(f"Scanning at {options.resolution_dpi} DPI ({mode_str})...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            raw = sorted(glob.glob(os.path.join(temp_dir, "page_*.pnm")))
            if not raw:
                self.last_error = (result.stderr or "").strip()[-500:]
                return False

            # Pages outlive this job's temp dir: the UI copies them on the GTK
            # main loop, after the worker has already cleaned up temp_dir.
            keep_dir = os.path.join(
                os.path.expanduser("~/.cache/ravenscan/pages"),
                time.strftime("%Y%m%d-%H%M%S"),
            )
            os.makedirs(keep_dir, exist_ok=True)
            for i, f in enumerate(raw):
                out = os.path.join(keep_dir, f"page_{i+1:03d}.png")
                conv = ["magick", f]
                if hw_dpi != options.resolution_dpi:
                    conv += ["-resize", f"{100.0 * options.resolution_dpi / hw_dpi:.4f}%"]
                conv += ["-density", str(options.resolution_dpi), out]
                subprocess.run(conv, check=True)
                if options.auto_deskew:
                    subprocess.run(["magick", out, "-deskew", "40%", out], check=True)
                side = ("Front" if i % 2 == 0 else "Back") if duplex else "Front"
                on_page(out, side)
            return True
        except Exception as e:
            self.last_error = str(e)
        return False

    def _run_simulation_scan(
        self,
        options: ScanOptions,
        temp_dir: str,
        on_status: Callable[[str], None],
        on_page: Callable[[str, str], None],
    ):
        """Generates realistic sample scanned document pages with test patterns and text."""
        pages_to_gen = 2 if options.source == ScanSource.ADF_DUPLEX else 1

        width = int(8.5 * options.resolution_dpi)
        height = int(11.0 * options.resolution_dpi)

        for p_idx in range(pages_to_gen):
            if self._cancel_requested:
                break

            side = "Front" if p_idx == 0 else "Back"
            on_status(f"Feeding page {p_idx+1} ({side} side)...")
            time.sleep(1.2)  # Simulate paper feeding delay

            page_file = os.path.join(temp_dir, f"sim_page_{p_idx+1}.png")
            date_str = time.strftime("%Y-%m-%d %H:%M:%S")

            color_bg = "white"
            if options.color_mode == ColorMode.GRAYSCALE:
                text_fill = "gray20"
                accent = "gray40"
            elif options.color_mode == ColorMode.LINEART:
                text_fill = "black"
                accent = "black"
            else:
                text_fill = "#1a1a2e"
                accent = "#4361ee"

            # Create realistic document with ImageMagick
            cmd = [
                "magick",
                "-size", f"{width}x{height}",
                f"xc:{color_bg}",
                # Header box
                "-fill", accent,
                "-draw", f"rectangle 100,100 {width-100},180",
                # Title
                "-fill", "white",
                "-pointsize", str(int(options.resolution_dpi * 0.16)),
                "-draw", f"text 140,155 'Raven Compact Scanner — Scanned Document'",
                # Metadata
                "-fill", text_fill,
                "-pointsize", str(int(options.resolution_dpi * 0.08)),
                "-draw", f"text 120,240 'Device: Raven Compact WiFi (Avision AD215W) | S/N: B10343501C170497'",
                "-draw", f"text 120,280 'Timestamp: {date_str} | Resolution: {options.resolution_dpi} DPI'",
                "-draw", f"text 120,320 'Page: {p_idx+1} of {pages_to_gen} ({side}) | Color Mode: {options.color_mode.value.title()}'",
                # Divider line
                "-stroke", "#cccccc", "-strokewidth", "2",
                "-draw", f"line 100,360 {width-100},360",
                "-stroke", "none",
                # Simulated paragraph text
                "-fill", text_fill,
                "-pointsize", str(int(options.resolution_dpi * 0.07)),
                "-draw", f"text 120,440 'This document was captured by Raven Desktop for Linux.'",
                "-draw", f"text 120,490 'The Raven Compact is an Avision AD215 series duplex document scanner.'",
                "-draw", f"text 120,540 'It features dual CIS sensors capable of simultaneous front and back scans at up to 600 DPI.'",
                "-draw", f"text 120,590 'All documents can be saved directly to searchable multi-page PDFs with Tesseract OCR.'",
                "-draw", f"text 120,640 'Page Side: {side.upper()} — Feed Verification: PASS'",
                # Border outline
                "-stroke", "#eeeeee", "-strokewidth", "4", "-fill", "none",
                "-draw", f"rectangle 40,40 {width-40},{height-40}",
                page_file,
            ]
            subprocess.run(cmd, check=True)

            if options.auto_deskew:
                on_status(f"Auto-deskewing page {p_idx+1}...")
                subprocess.run(["magick", page_file, "-deskew", "40%", page_file], check=True)

            on_page(page_file, side)
