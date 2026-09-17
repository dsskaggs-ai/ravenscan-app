#!/usr/bin/env python3
"""
Document and page session management for RavenScan.
Handles page ordering, rotation, thumbnail generation, and caching.
"""

import os
import shutil
import tempfile
import subprocess
from datetime import datetime
from typing import List, Optional, Callable

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

class ScannedPage:
    def __init__(self, original_image_path: str, page_number: int, side: str = "Front", dpi: int = 300):
        self.page_number = page_number
        self.side = side  # "Front", "Back", or "Page"
        self.rotation = 0  # 0, 90, 180, 270
        self.dpi = dpi

        # Store in session temporary directory
        self.temp_dir = os.path.dirname(original_image_path)
        self.image_path = original_image_path
        self.thumbnail_path = os.path.join(self.temp_dir, f"thumb_{os.path.basename(original_image_path)}")

        self._generate_thumbnail()

    def _generate_thumbnail(self):
        """Generates a 220px height thumbnail for the sidebar gallery."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.image_path)
            width = pixbuf.get_width()
            height = pixbuf.get_height()
            target_h = 240
            target_w = int((width / height) * target_h)
            thumb = pixbuf.scale_simple(target_w, target_h, GdkPixbuf.InterpType.BILINEAR)
            thumb.savev(self.thumbnail_path, "png", [], [])
        except Exception as e:
            print(f"[Document] Thumbnail generation error: {e}")
            # Fallback to copy if pixbuf fails
            shutil.copyfile(self.image_path, self.thumbnail_path)

    def rotate_clockwise(self):
        """Rotates image 90 degrees clockwise."""
        self.rotation = (self.rotation + 90) % 360
        self._apply_rotation_to_file(90)

    def rotate_counterclockwise(self):
        """Rotates image 90 degrees counter-clockwise."""
        self.rotation = (self.rotation - 90) % 360
        self._apply_rotation_to_file(270)

    def _apply_rotation_to_file(self, degrees: int):
        try:
            # Rotate with ImageMagick convert or magick
            cmd = ["magick", self.image_path, "-rotate", str(degrees), self.image_path]
            subprocess.run(cmd, check=True)
            self._generate_thumbnail()
        except Exception as e:
            print(f"[Document] Error rotating page {self.page_number}: {e}")

    def deskew(self):
        """Applies auto-deskew correction using ImageMagick."""
        try:
            cmd = ["magick", self.image_path, "-deskew", "40%", self.image_path]
            subprocess.run(cmd, check=True)
            self._generate_thumbnail()
        except Exception as e:
            print(f"[Document] Error deskewing page: {e}")


class DocumentSession:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="ravenscan_session_")
        self.pages: List[ScannedPage] = []
        self.selected_index: int = 0
        self.on_pages_changed: Optional[Callable[[], None]] = None

    def add_scanned_image(self, file_path: str, side: str = "Front", dpi: int = 300) -> ScannedPage:
        """Adds a newly scanned image into the current session."""
        page_num = len(self.pages) + 1
        dest_filename = f"page_{page_num:03d}_{side.lower()}.png"
        dest_path = os.path.join(self.temp_dir, dest_filename)
        shutil.copyfile(file_path, dest_path)

        page = ScannedPage(dest_path, page_num, side=side, dpi=dpi)
        self.pages.append(page)
        self.selected_index = len(self.pages) - 1

        if self.on_pages_changed:
            self.on_pages_changed()

        return page

    def get_selected_page(self) -> Optional[ScannedPage]:
        if 0 <= self.selected_index < len(self.pages):
            return self.pages[self.selected_index]
        return None

    def remove_page(self, index: int):
        if 0 <= index < len(self.pages):
            page = self.pages.pop(index)
            try:
                if os.path.exists(page.image_path):
                    os.remove(page.image_path)
                if os.path.exists(page.thumbnail_path):
                    os.remove(page.thumbnail_path)
            except Exception:
                pass

            # Renumber pages
            for i, p in enumerate(self.pages):
                p.page_number = i + 1

            if self.selected_index >= len(self.pages):
                self.selected_index = max(0, len(self.pages) - 1)

            if self.on_pages_changed:
                self.on_pages_changed()

    def move_page_up(self, index: int):
        if index > 0 and index < len(self.pages):
            self.pages[index - 1], self.pages[index] = self.pages[index], self.pages[index - 1]
            self._renumber()
            self.selected_index = index - 1
            if self.on_pages_changed:
                self.on_pages_changed()

    def move_page_down(self, index: int):
        if index >= 0 and index < len(self.pages) - 1:
            self.pages[index + 1], self.pages[index] = self.pages[index], self.pages[index + 1]
            self._renumber()
            self.selected_index = index + 1
            if self.on_pages_changed:
                self.on_pages_changed()

    def _renumber(self):
        for i, p in enumerate(self.pages):
            p.page_number = i + 1

    def clear(self):
        """Clears all pages in the current session."""
        for page in self.pages:
            try:
                if os.path.exists(page.image_path):
                    os.remove(page.image_path)
                if os.path.exists(page.thumbnail_path):
                    os.remove(page.thumbnail_path)
            except Exception:
                pass
        self.pages.clear()
        self.selected_index = 0
        if self.on_pages_changed:
            self.on_pages_changed()

    def cleanup(self):
        self.clear()
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception:
            pass
