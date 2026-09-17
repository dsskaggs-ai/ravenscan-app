#!/usr/bin/env python3
"""
Interactive document preview widget for RavenScan.
Displays the currently selected scanned page with zoom and pan support.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GdkPixbuf, Gio, GLib

from ravenscan.document import ScannedPage
from typing import Optional

class DocumentPreview(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.current_page: Optional[ScannedPage] = None
        self.zoom_level = 1.0  # 1.0 = Fit to width/height

        # Top preview toolbar
        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.toolbar.set_margin_top(6)
        self.toolbar.set_margin_bottom(6)
        self.toolbar.set_margin_start(12)
        self.toolbar.set_margin_end(12)

        self.page_info_label = Gtk.Label(label="No document scanned")
        self.page_info_label.set_halign(Gtk.Align.START)
        self.page_info_label.add_css_class("dim-label")
        self.toolbar.append(self.page_info_label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.toolbar.append(spacer)

        # Zoom buttons
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        zoom_box.add_css_class("linked")

        self.btn_zoom_out = Gtk.Button(icon_name="zoom-out-symbolic")
        self.btn_zoom_out.set_tooltip_text("Zoom Out")
        self.btn_zoom_out.connect("clicked", self._on_zoom_out)
        zoom_box.append(self.btn_zoom_out)

        self.btn_zoom_fit = Gtk.Button(icon_name="zoom-fit-best-symbolic")
        self.btn_zoom_fit.set_tooltip_text("Fit to View")
        self.btn_zoom_fit.connect("clicked", self._on_zoom_fit)
        zoom_box.append(self.btn_zoom_fit)

        self.btn_zoom_in = Gtk.Button(icon_name="zoom-in-symbolic")
        self.btn_zoom_in.set_tooltip_text("Zoom In")
        self.btn_zoom_in.connect("clicked", self._on_zoom_in)
        zoom_box.append(self.btn_zoom_in)

        self.toolbar.append(zoom_box)

        # Rotate buttons
        rotate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        rotate_box.add_css_class("linked")

        self.btn_rot_left = Gtk.Button(icon_name="object-rotate-left-symbolic")
        self.btn_rot_left.set_tooltip_text("Rotate Left (90°)")
        self.btn_rot_left.connect("clicked", self._on_rotate_left)
        rotate_box.append(self.btn_rot_left)

        self.btn_rot_right = Gtk.Button(icon_name="object-rotate-right-symbolic")
        self.btn_rot_right.set_tooltip_text("Rotate Right (90°)")
        self.btn_rot_right.connect("clicked", self._on_rotate_right)
        rotate_box.append(self.btn_rot_right)

        self.toolbar.append(rotate_box)

        self.append(self.toolbar)

        # Scrolled picture container
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_hexpand(True)
        self.scrolled_window.set_vexpand(True)
        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_halign(Gtk.Align.CENTER)
        self.picture.set_valign(Gtk.Align.CENTER)
        self.picture.add_css_class("card")
        self.picture.set_margin_top(16)
        self.picture.set_margin_bottom(16)
        self.picture.set_margin_start(16)
        self.picture.set_margin_end(16)

        # Empty state placeholder
        self.placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.placeholder.set_halign(Gtk.Align.CENTER)
        self.placeholder.set_valign(Gtk.Align.CENTER)
        self.placeholder.set_hexpand(True)
        self.placeholder.set_vexpand(True)

        empty_icon = Gtk.Image.new_from_icon_name("scanner-symbolic")
        empty_icon.set_pixel_size(72)
        empty_icon.add_css_class("dim-label")
        self.placeholder.append(empty_icon)

        empty_label = Gtk.Label(label="Load paper into the ADF and click 'Scan Duplex' or 'Scan Single'")
        empty_label.add_css_class("title-4")
        empty_label.add_css_class("dim-label")
        self.placeholder.append(empty_label)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.placeholder, "placeholder")

        view_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        view_container.append(self.picture)
        self.scrolled_window.set_child(view_container)
        self.stack.add_named(self.scrolled_window, "viewer")

        self.append(self.stack)
        self.stack.set_visible_child_name("placeholder")

        self.on_rotate_callback = None

    def display_page(self, page: Optional[ScannedPage]):
        self.current_page = page
        if not page:
            self.stack.set_visible_child_name("placeholder")
            self.page_info_label.set_text("No document scanned")
            self.btn_rot_left.set_sensitive(False)
            self.btn_rot_right.set_sensitive(False)
            self.btn_zoom_in.set_sensitive(False)
            self.btn_zoom_out.set_sensitive(False)
            self.btn_zoom_fit.set_sensitive(False)
            return

        self.btn_rot_left.set_sensitive(True)
        self.btn_rot_right.set_sensitive(True)
        self.btn_zoom_in.set_sensitive(True)
        self.btn_zoom_out.set_sensitive(True)
        self.btn_zoom_fit.set_sensitive(True)

        self.stack.set_visible_child_name("viewer")
        gfile = Gio.File.new_for_path(page.image_path)
        self.picture.set_file(gfile)

        info = f"Page {page.page_number} ({page.side}) • {page.dpi} DPI"
        if page.rotation != 0:
            info += f" • Rotated {page.rotation}°"
        self.page_info_label.set_text(info)

    def _on_zoom_in(self, button):
        self.zoom_level = min(3.0, self.zoom_level + 0.25)
        self._apply_zoom()

    def _on_zoom_out(self, button):
        self.zoom_level = max(0.25, self.zoom_level - 0.25)
        self._apply_zoom()

    def _on_zoom_fit(self, button):
        self.zoom_level = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        if not self.current_page:
            return
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.current_page.image_path)
        w = int(pixbuf.get_width() * self.zoom_level * 0.4)
        h = int(pixbuf.get_height() * self.zoom_level * 0.4)
        scaled = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        self.picture.set_pixbuf(scaled)

    def _on_rotate_left(self, button):
        if self.current_page:
            self.current_page.rotate_counterclockwise()
            self.display_page(self.current_page)
            if self.on_rotate_callback:
                self.on_rotate_callback(self.current_page)

    def _on_rotate_right(self, button):
        if self.current_page:
            self.current_page.rotate_clockwise()
            self.display_page(self.current_page)
            if self.on_rotate_callback:
                self.on_rotate_callback(self.current_page)
