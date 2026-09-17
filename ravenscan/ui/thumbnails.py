#!/usr/bin/env python3
"""
Thumbnail strip widget for RavenScan.
Shows scrollable list of scanned pages with page numbers and actions.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GObject

from ravenscan.document import DocumentSession, ScannedPage
from typing import Callable, Optional

class PageThumbnailRow(Gtk.ListBoxRow):
    def __init__(self, page: ScannedPage, index: int, on_delete: Callable[[int], None], on_rotate: Callable[[int], None]):
        super().__init__()
        self.page = page
        self.index = index
        self.on_delete = on_delete
        self.on_rotate = on_rotate

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.add_css_class("card")

        # Picture
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_size_request(160, 210)
        self.picture.set_halign(Gtk.Align.CENTER)
        gfile = Gio.File.new_for_path(page.thumbnail_path)
        self.picture.set_file(gfile)
        box.append(self.picture)

        # Label & controls box
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ctrl_box.set_halign(Gtk.Align.CENTER)

        badge_text = f"Page {page.page_number} ({page.side})"
        label = Gtk.Label(label=badge_text)
        label.add_css_class("caption")
        label.add_css_class("heading")
        ctrl_box.append(label)

        btn_rot = Gtk.Button(icon_name="object-rotate-right-symbolic")
        btn_rot.set_tooltip_text("Rotate 90°")
        btn_rot.add_css_class("flat")
        btn_rot.connect("clicked", lambda b: self.on_rotate(self.index))
        ctrl_box.append(btn_rot)

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.set_tooltip_text("Delete Page")
        btn_del.add_css_class("flat")
        btn_del.connect("clicked", lambda b: self.on_delete(self.index))
        ctrl_box.append(btn_del)

        box.append(ctrl_box)
        self.set_child(box)

    def refresh(self):
        gfile = Gio.File.new_for_path(self.page.thumbnail_path)
        self.picture.set_file(gfile)


class ThumbnailStrip(Gtk.Box):
    def __init__(self, session: DocumentSession, on_page_selected: Callable[[int], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.session = session
        self.on_page_selected = on_page_selected

        self.set_size_request(220, -1)
        self.set_vexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_top(8)
        header.set_margin_bottom(4)
        header.set_margin_start(12)
        header.set_margin_end(12)

        self.count_label = Gtk.Label(label="Pages (0)")
        self.count_label.add_css_class("title-4")
        header.append(self.count_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        self.append(header)

        # Scrolled container for list
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_vexpand(True)
        self.scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-selected", self._on_row_selected)
        self.list_box.add_css_class("navigation-sidebar")

        self.scrolled.set_child(self.list_box)
        self.append(self.scrolled)

    def update_pages(self):
        """Rebuilds the thumbnail list according to current session state."""
        # Clear existing rows
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)

        self.count_label.set_text(f"Pages ({len(self.session.pages)})")

        for idx, page in enumerate(self.session.pages):
            row = PageThumbnailRow(
                page=page,
                index=idx,
                on_delete=self._delete_page,
                on_rotate=self._rotate_page
            )
            self.list_box.append(row)

        if self.session.pages:
            target_idx = min(self.session.selected_index, len(self.session.pages) - 1)
            row = self.list_box.get_row_at_index(target_idx)
            if row:
                self.list_box.select_row(row)

    def _on_row_selected(self, list_box, row):
        if row is not None:
            self.session.selected_index = row.index
            self.on_page_selected(row.index)

    def _delete_page(self, index: int):
        self.session.remove_page(index)
        self.update_pages()

    def _rotate_page(self, index: int):
        if 0 <= index < len(self.session.pages):
            self.session.pages[index].rotate_clockwise()
            row = self.list_box.get_row_at_index(index)
            if row:
                row.refresh()
            self.on_page_selected(index)
