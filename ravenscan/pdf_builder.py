#!/usr/bin/env python3
"""
PDF Builder and Document Exporter for RavenScan.
Combines scanned pages into searchable PDFs (via Tesseract) or standard PDFs.
"""

import os
import shutil
import tempfile
import subprocess
from datetime import datetime
from typing import List, Optional

from ravenscan.document import ScannedPage

DEFAULT_SCAN_DIR = os.path.expanduser("~/Documents/Scans")

class PdfBuilder:
    @staticmethod
    def sanitize_filename(name: str) -> str:
        clean = "".join(c for c in name if c.isalnum() or c in (" ", "_", "-", ".")).strip()
        return clean if clean else "Scan"

    @classmethod
    def generate_filename(cls, base_name: str = "Scan", append_date: bool = True, extension: str = "pdf", directory: Optional[str] = None) -> str:
        safe_name = cls.sanitize_filename(base_name)
        if append_date:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"{safe_name}_{timestamp}.{extension}"
        else:
            filename = f"{safe_name}.{extension}"

        if directory and os.path.exists(directory):
            candidate = os.path.join(directory, filename)
            counter = 1
            name_part = f"{safe_name}_{timestamp}" if append_date else safe_name
            while os.path.exists(candidate):
                filename = f"{name_part}_{counter}.{extension}"
                candidate = os.path.join(directory, filename)
                counter += 1

        return filename

    @staticmethod
    def get_default_filename(extension: str = "pdf") -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return f"Scan_{timestamp}.{extension}"

    @staticmethod
    def ensure_default_dir() -> str:
        from ravenscan.config import ConfigManager
        path = ConfigManager.get_save_dir()
        os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def export_pdf(cls, pages: List[ScannedPage], output_path: str, ocr: bool = False, progress_cb=None) -> str:
        """
        Exports list of ScannedPage into a multi-page PDF.
        If ocr is True, runs Tesseract OCR to produce a searchable PDF with text overlay.
        """
        if not pages:
            raise ValueError("No pages to export.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if ocr and shutil.which("tesseract"):
            return cls._export_ocr_pdf(pages, output_path, progress_cb)
        else:
            return cls._export_standard_pdf(pages, output_path, progress_cb)

    @classmethod
    def _export_standard_pdf(cls, pages: List[ScannedPage], output_path: str, progress_cb=None) -> str:
        """Generates multi-page PDF using ImageMagick."""
        image_paths = [p.image_path for p in pages]
        
        # ImageMagick convert to PDF
        # We set -density 300 to preserve document scale
        cmd = ["magick"]
        for p in pages:
            cmd.extend(["-density", str(p.dpi), p.image_path])
        cmd.extend(["-compress", "jpeg", "-quality", "85", output_path])

        if progress_cb:
            progress_cb("Assembling multi-page PDF...")

        subprocess.run(cmd, check=True)
        return output_path

    @classmethod
    def _export_ocr_pdf(cls, pages: List[ScannedPage], output_path: str, progress_cb=None) -> str:
        """Generates searchable multi-page PDF using Tesseract OCR."""
        temp_dir = tempfile.mkdtemp(prefix="ravenscan_ocr_")
        page_pdfs = []

        try:
            for i, p in enumerate(pages):
                if progress_cb:
                    progress_cb(f"Performing OCR on page {i+1} of {len(pages)}...")

                base_out = os.path.join(temp_dir, f"ocr_page_{i:03d}")
                # tesseract input base_out -l eng pdf
                cmd = ["tesseract", p.image_path, base_out, "-l", "eng", "--dpi", str(p.dpi), "pdf"]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                page_pdfs.append(f"{base_out}.pdf")

            if progress_cb:
                progress_cb("Merging searchable pages...")

            if len(page_pdfs) == 1:
                shutil.copyfile(page_pdfs[0], output_path)
            else:
                # Merge using pdfunite or gs
                if shutil.which("pdfunite"):
                    subprocess.run(["pdfunite"] + page_pdfs + [output_path], check=True)
                else:
                    # Ghostscript fallback
                    cmd = ["gs", "-dBATCH", "-dNOPAUSE", "-q", "-sDEVICE=pdfwrite",
                           f"-sOutputFile={output_path}"] + page_pdfs
                    subprocess.run(cmd, check=True)

            return output_path
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def export_images(cls, pages: List[ScannedPage], output_dir: str, prefix: str = "Scan", fmt: str = "png") -> List[str]:
        """Exports pages as individual image files."""
        os.makedirs(output_dir, exist_ok=True)
        exported = []
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

        for i, p in enumerate(pages):
            out_file = os.path.join(output_dir, f"{prefix}_{timestamp}_page{i+1:02d}.{fmt}")
            if fmt.lower() == "png":
                shutil.copyfile(p.image_path, out_file)
            else:
                subprocess.run(["magick", p.image_path, out_file], check=True)
            exported.append(out_file)

        return exported
