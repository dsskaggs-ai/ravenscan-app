#!/usr/bin/env python3
"""
Permission helper dialog for RavenScan.
Guides user on granting USB udev permissions for the scanner.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

class PermissionDialog(Adw.Window):
    def __init__(self, parent_window, fix_command: str):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title("Scanner USB Permissions")
        self.set_default_size(520, 360)

        self.fix_command = fix_command

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(56)
        icon.add_css_class("warning")
        content.append(icon)

        title = Gtk.Label(label="USB Permissions Needed")
        title.add_css_class("title-2")
        content.append(title)

        desc = Gtk.Label(
            label="Your Raven Compact Scanner was found on the USB bus,\n"
                  "but Linux requires a udev rule to allow your user account to communicate with it.\n"
                  "Run this one-time command in your terminal:"
        )
        desc.set_justify(Gtk.Justification.CENTER)
        desc.add_css_class("dim-label")
        content.append(desc)

        # Command entry
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_text(self.fix_command)
        self.entry.set_editable(False)
        self.entry.set_hexpand(True)
        cmd_box.append(self.entry)

        btn_copy = Gtk.Button(label="Copy")
        btn_copy.add_css_class("suggested-action")
        btn_copy.connect("clicked", self._on_copy_clicked)
        cmd_box.append(btn_copy)

        content.append(cmd_box)

        self.feedback_label = Gtk.Label(label="")
        self.feedback_label.add_css_class("caption")
        content.append(self.feedback_label)

        # Or run helper script
        helper_note = Gtk.Label(
            label="Or simply run in terminal: ravenscan-setup"
        )
        helper_note.add_css_class("caption")
        helper_note.add_css_class("dim-label")
        content.append(helper_note)

        btn_close = Gtk.Button(label="Close")
        btn_close.set_halign(Gtk.Align.CENTER)
        btn_close.connect("clicked", lambda b: self.destroy())
        content.append(btn_close)

        self.set_content(content)

    def _on_copy_clicked(self, button):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self.fix_command)
        self.feedback_label.set_text("✅ Copied to clipboard! Paste and run in terminal.")
        self.feedback_label.add_css_class("success")
