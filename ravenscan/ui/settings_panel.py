#!/usr/bin/env python3
"""
Scanner settings and options sidebar panel for RavenScan.
Provides Libadwaita preference rows for configuring File Destination (Google Drive & Local),
DPI, Color, Duplex, OCR, and Document Name.
"""

import os
import subprocess
from typing import Dict, Any, List

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from ravenscan.hardware import ColorMode, ScanSource, PaperSize
from ravenscan.scanner import ScanOptions
from ravenscan.config import ConfigManager, GDRIVE_DIR, GDRIVE_RAVEN_DIR


class SettingsPanel(Gtk.Box):
    def __init__(self, parent_window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window
        self.set_size_request(330, -1)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)

        # Load persisted config
        self.config = ConfigManager.load()
        self.save_dir = ConfigManager.get_save_dir()
        self.destinations: List[Dict[str, Any]] = []
        self._updating_destinations = False
        self._previous_selected_index = 0

        # Scrolled container for settings
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(380)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(box)
        scrolled.set_child(clamp)
        self.append(scrolled)

        # 1. Device Info Group
        self.device_group = Adw.PreferencesGroup()
        self.device_group.set_title("Scanner Hardware")

        self.device_row = Adw.ActionRow()
        self.device_row.set_title("Raven Compact WiFi")
        self.device_row.set_subtitle("Avision AD215W • USB")
        self.device_icon = Gtk.Image.new_from_icon_name("scanner-symbolic")
        self.device_row.add_prefix(self.device_icon)

        self.status_badge = Gtk.Label(label="Checking...")
        self.status_badge.add_css_class("caption")
        self.status_badge.add_css_class("dim-label")
        self.device_row.add_suffix(self.status_badge)

        self.device_group.add(self.device_row)
        box.append(self.device_group)

        # 2. File & Destination Group
        self.file_group = Adw.PreferencesGroup()
        self.file_group.set_title("File &amp; Destination")
        self.file_group.set_description("Configure document name and Google Drive save location")

        # Document Name Entry
        self.doc_name_row = Adw.EntryRow()
        self.doc_name_row.set_title("Document Name")
        self.doc_name_row.set_text(self.config.get("doc_name", "Scan"))
        self._doc_name_save_id = None
        self.doc_name_row.connect("changed", self._on_doc_name_changed)
        self.doc_name_row.connect("apply", self._on_doc_name_applied)
        self.file_group.add(self.doc_name_row)

        # Destination Folder Selector (Searchable ComboRow)
        self.dest_combo_row = Adw.ComboRow()
        self.dest_combo_row.set_title("Destination Folder")
        self.dest_combo_row.set_subtitle("Google Drive or local folder")
        self.dest_combo_row.set_enable_search(True)
        self.file_group.add(self.dest_combo_row)

        # Active Path ActionRow with quick buttons
        self.path_row = Adw.ActionRow()
        self.path_row.set_title("Save Location")
        self.path_icon = Gtk.Image.new_from_icon_name("folder-remote-symbolic")
        self.path_row.add_prefix(self.path_icon)

        path_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

        # Add Subfolder in Google Drive button
        self.btn_add_folder = Gtk.Button(icon_name="list-add-symbolic")
        self.btn_add_folder.set_tooltip_text("Create new subfolder in Google Drive")
        self.btn_add_folder.add_css_class("flat")
        self.btn_add_folder.connect("clicked", self._on_add_subfolder_clicked)
        path_btn_box.append(self.btn_add_folder)

        # Browse filesystem button
        self.btn_browse = Gtk.Button(icon_name="folder-open-symbolic")
        self.btn_browse.set_tooltip_text("Browse filesystem for folder...")
        self.btn_browse.add_css_class("flat")
        self.btn_browse.connect("clicked", self._on_choose_folder_clicked)
        path_btn_box.append(self.btn_browse)

        # Refresh Google Drive folders button
        self.btn_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        self.btn_refresh.set_tooltip_text("Refresh Google Drive folders")
        self.btn_refresh.add_css_class("flat")
        self.btn_refresh.connect("clicked", self._on_refresh_clicked)
        path_btn_box.append(self.btn_refresh)

        # Open in file manager button
        self.btn_open_dir = Gtk.Button(icon_name="folder-symbolic")
        self.btn_open_dir.set_tooltip_text("Open current destination in Files")
        self.btn_open_dir.add_css_class("flat")
        self.btn_open_dir.connect("clicked", self._on_open_dir_clicked)
        path_btn_box.append(self.btn_open_dir)

        self.path_row.add_suffix(path_btn_box)
        self.file_group.add(self.path_row)

        # Append Date & Time Switch
        self.append_date_switch = Adw.SwitchRow()
        self.append_date_switch.set_title("Append Date &amp; Time")
        self.append_date_switch.set_subtitle("Adds timestamp (e.g. _2026-09-14) so files don't overwrite")
        self.append_date_switch.set_active(self.config.get("append_date", True))
        self.append_date_switch.connect("notify::active", self._on_append_date_changed)
        self.file_group.add(self.append_date_switch)

        box.append(self.file_group)

        # 3. Scan Settings Group
        self.settings_group = Adw.PreferencesGroup()
        self.settings_group.set_title("Scan Settings")

        # Source (Duplex / Simplex)
        self.source_row = Adw.ComboRow()
        self.source_row.set_title("Scan Source")
        self.source_model = Gtk.StringList.new([
            "Double-Sided (Duplex ADF)",
            "Single-Sided (Simplex ADF)",
            "Card Slot"
        ])
        self.source_row.set_model(self.source_model)
        self.source_row.set_selected(self.config.get("source_idx", 0))
        self.source_row.connect("notify::selected", self._on_setting_changed)
        self.settings_group.add(self.source_row)

        # Resolution DPI
        self.dpi_row = Adw.ComboRow()
        self.dpi_row.set_title("Resolution")
        self.dpi_model = Gtk.StringList.new([
            "150 DPI (Fast / Draft)",
            "200 DPI (Standard)",
            "300 DPI (High Quality / OCR)",
            "600 DPI (Ultra Detail)"
        ])
        self.dpi_row.set_model(self.dpi_model)
        self.dpi_row.set_selected(self.config.get("resolution_idx", 2))
        self.dpi_row.connect("notify::selected", self._on_setting_changed)
        self.settings_group.add(self.dpi_row)

        # Color Mode
        self.color_row = Adw.ComboRow()
        self.color_row.set_title("Color Mode")
        self.color_model = Gtk.StringList.new([
            "Color (24-bit RGB)",
            "Grayscale (8-bit)",
            "Black & White (1-bit Lineart)"
        ])
        self.color_row.set_model(self.color_model)
        self.color_row.set_selected(self.config.get("color_mode_idx", 0))
        self.color_row.connect("notify::selected", self._on_setting_changed)
        self.settings_group.add(self.color_row)

        # Paper Size
        self.size_row = Adw.ComboRow()
        self.size_row.set_title("Paper Size")
        self.size_model = Gtk.StringList.new([
            "Auto-Detect / Crop",
            "US Letter (8.5 x 11 in)",
            "US Legal (8.5 x 14 in)",
            "A4 (210 x 297 mm)"
        ])
        self.size_row.set_model(self.size_model)
        self.size_row.set_selected(self.config.get("paper_size_idx", 1))
        self.size_row.connect("notify::selected", self._on_setting_changed)
        self.settings_group.add(self.size_row)

        box.append(self.settings_group)

        # 4. Processing Group
        self.proc_group = Adw.PreferencesGroup()
        self.proc_group.set_title("Post-Processing")

        self.deskew_switch = Adw.SwitchRow()
        self.deskew_switch.set_title("Auto-Deskew")
        self.deskew_switch.set_subtitle("Automatically straighten tilted pages")
        self.deskew_switch.set_active(self.config.get("auto_deskew", True))
        self.deskew_switch.connect("notify::active", self._on_setting_changed)
        self.proc_group.add(self.deskew_switch)

        self.ocr_switch = Adw.SwitchRow()
        self.ocr_switch.set_title("Searchable PDF (OCR)")
        self.ocr_switch.set_subtitle("Embed searchable text using Tesseract")
        self.ocr_switch.set_active(self.config.get("ocr", True))
        self.ocr_switch.connect("notify::active", self._on_setting_changed)
        self.proc_group.add(self.ocr_switch)

        box.append(self.proc_group)

        # Populate destinations and bind selection
        self._refresh_destinations()
        self._update_path_row()
        self.dest_combo_row.connect("notify::selected", self._on_destination_selected)

    def _refresh_destinations(self):
        """Populates the destination combo model with Google Drive & local folders."""
        self._updating_destinations = True
        try:
            self.destinations = ConfigManager.get_available_destinations()
            labels = [d["label"] for d in self.destinations]
            model = Gtk.StringList.new(labels)
            self.dest_combo_row.set_model(model)

            # Select matching path
            selected_idx = 0
            for idx, d in enumerate(self.destinations):
                if d.get("path") == self.save_dir:
                    selected_idx = idx
                    break

            self.dest_combo_row.set_selected(selected_idx)
            self._previous_selected_index = selected_idx
        finally:
            self._updating_destinations = False

    def _sync_combo_selection(self, target_path: str):
        """Syncs the combo row to the given target path."""
        self._updating_destinations = True
        try:
            for idx, d in enumerate(self.destinations):
                if d.get("path") == target_path:
                    self.dest_combo_row.set_selected(idx)
                    self._previous_selected_index = idx
                    return

            # If not found, refresh and retry
            self._refresh_destinations()
            for idx, d in enumerate(self.destinations):
                if d.get("path") == target_path:
                    self.dest_combo_row.set_selected(idx)
                    self._previous_selected_index = idx
                    return
        finally:
            self._updating_destinations = False

    def _update_path_row(self):
        """Updates the path display row with friendly label and icon."""
        disp = ConfigManager.format_display_path(self.save_dir)
        escaped = GLib.markup_escape_text(disp)
        self.path_row.set_subtitle(escaped)

        if self.save_dir.startswith(GDRIVE_DIR):
            self.path_icon.set_from_icon_name("folder-remote-symbolic")
        else:
            self.path_icon.set_from_icon_name("folder-documents-symbolic")

    def set_destination(self, path: str):
        """Sets the active save directory, saves config, and updates UI."""
        resolved = os.path.abspath(os.path.expanduser(path))
        self.save_dir = resolved
        self.config["save_dir"] = resolved
        ConfigManager.set_save_dir(resolved)
        self._update_path_row()
        self._sync_combo_selection(resolved)

    def _on_destination_selected(self, combo, gparam):
        if self._updating_destinations:
            return

        idx = combo.get_selected()
        if idx < 0 or idx >= len(self.destinations):
            return

        selected_dest = self.destinations[idx]

        if selected_dest.get("path") == "__BROWSE__":
            # User chose "Browse Other Folder..."
            self._on_choose_folder_clicked()
            return

        self._previous_selected_index = idx
        self.set_destination(selected_dest["path"])

    def _on_doc_name_changed(self, entry):
        """Updates config in memory; disk write debounced (500ms) to avoid a write per keystroke."""
        self.config["doc_name"] = entry.get_text().strip()
        if self._doc_name_save_id is not None:
            GLib.source_remove(self._doc_name_save_id)
        self._doc_name_save_id = GLib.timeout_add(500, self._flush_doc_name)

    def _flush_doc_name(self):
        ConfigManager.save(self.config)
        self._doc_name_save_id = None
        return GLib.SOURCE_REMOVE

    def _on_doc_name_applied(self, entry):
        """User pressed Enter — flush immediately, cancelling any pending debounce."""
        if self._doc_name_save_id is not None:
            GLib.source_remove(self._doc_name_save_id)
        self._flush_doc_name()

    def _on_append_date_changed(self, switch, gparam):
        self.config["append_date"] = switch.get_active()
        ConfigManager.save(self.config)

    def _on_setting_changed(self, widget, gparam):
        self.config["source_idx"] = self.source_row.get_selected()
        self.config["resolution_idx"] = self.dpi_row.get_selected()
        self.config["color_mode_idx"] = self.color_row.get_selected()
        self.config["paper_size_idx"] = self.size_row.get_selected()
        self.config["auto_deskew"] = self.deskew_switch.get_active()
        self.config["ocr"] = self.ocr_switch.get_active()
        ConfigManager.save(self.config)

    def _on_choose_folder_clicked(self, button=None):
        """Opens native folder chooser dialog to select destination."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose Destination Folder for Scans")
        ConfigManager.heal_mount_if_needed(self.save_dir)

        initial_dir = self.save_dir if os.path.isdir(self.save_dir) else GDRIVE_DIR
        if not os.path.isdir(initial_dir):
            initial_dir = os.path.expanduser("~")

        dialog.set_initial_folder(Gio.File.new_for_path(initial_dir))

        def folder_selected_callback(dialog_obj, result):
            try:
                folder = dialog_obj.select_folder_finish(result)
            except GLib.Error as err:
                # Gtk.DialogError.DISMISSED == user cancelled; anything else is real
                dismissed = getattr(Gtk.DialogError, "DISMISSED", 2)
                if not (err.domain == "gtk-dialog-error-quark" and err.code == dismissed):
                    print(f"Folder selection failed: {err}")
                self._sync_combo_selection(self.save_dir)
                return

            if folder:
                path = folder.get_path()
                if not path and folder.get_uri():
                    try:
                        path, _ = GLib.filename_from_uri(folder.get_uri())
                    except GLib.Error as err:
                        print(f"Could not resolve folder URI: {err}")
                        path = None
                if path and os.path.isdir(path):
                    self.set_destination(path)
                    return

            print("Folder selection returned no usable path; reverting")
            self._sync_combo_selection(self.save_dir)

        dialog.select_folder(self.parent_window, None, folder_selected_callback)

    def _on_add_subfolder_clicked(self, button=None):
        """Opens a clean dialog to create a new folder inside Google Drive."""
        dialog = Adw.AlertDialog(
            heading="Create Folder in Google Drive",
            body="Enter a name for the new folder:"
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("e.g. 2026 Receipts")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        def on_response(diag, response):
            if response == "create":
                name = entry.get_text().strip()
                if name:
                    try:
                        new_path = ConfigManager.create_new_folder(name, self.save_dir)
                        self._refresh_destinations()
                        self.set_destination(new_path)
                    except Exception as ex:
                        print(f"Error creating folder: {ex}")

        dialog.choose(self.parent_window, None, on_response)

    def _on_refresh_clicked(self, button=None):
        """Refreshes available Google Drive destinations."""
        ConfigManager.heal_mount_if_needed()
        self._refresh_destinations()
        self._sync_combo_selection(self.save_dir)

    def _on_open_dir_clicked(self, button=None):
        """Opens current save directory in system file manager."""
        ConfigManager.heal_mount_if_needed(self.save_dir)
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            subprocess.Popen(["xdg-open", self.save_dir])
        except Exception as e:
            print(f"Error opening directory: {e}")

    def get_options(self) -> ScanOptions:
        # Source
        source_idx = self.source_row.get_selected()
        source = ScanSource.ADF_DUPLEX if source_idx == 0 else (
            ScanSource.ADF_SIMPLEX if source_idx == 1 else ScanSource.CARD_SLOT
        )

        # DPI
        dpi_map = [150, 200, 300, 600]
        dpi = dpi_map[self.dpi_row.get_selected()]

        # Color
        color_idx = self.color_row.get_selected()
        color = ColorMode.COLOR if color_idx == 0 else (
            ColorMode.GRAYSCALE if color_idx == 1 else ColorMode.LINEART
        )

        # Size
        size_map = [PaperSize.AUTO, PaperSize.LETTER, PaperSize.LEGAL, PaperSize.A4]
        paper_size = size_map[self.size_row.get_selected()]

        # Document name
        doc_name = self.doc_name_row.get_text().strip()
        if not doc_name:
            doc_name = "Scan"

        return ScanOptions(
            color_mode=color,
            resolution_dpi=dpi,
            source=source,
            paper_size=paper_size,
            auto_deskew=self.deskew_switch.get_active(),
            remove_blank_pages=False,
            ocr=self.ocr_switch.get_active(),
            document_name=doc_name,
            save_dir=self.save_dir,
            append_date=self.append_date_switch.get_active(),
        )

    def set_device_status(self, is_connected: bool, is_writable: bool, device_name: str, serial: str):
        if not is_connected:
            self.device_row.set_title("Scanner Disconnected")
            self.device_row.set_subtitle("Please plug in Raven Compact via USB")
            self.status_badge.set_text("Offline")
            self.status_badge.remove_css_class("success")
            self.status_badge.remove_css_class("warning")
            self.status_badge.add_css_class("error")
        elif not is_writable:
            self.device_row.set_title(device_name)
            self.device_row.set_subtitle(f"S/N: {serial} • USB Permissions Needed")
            self.status_badge.set_text("Permissions Needed")
            self.status_badge.remove_css_class("success")
            self.status_badge.remove_css_class("error")
            self.status_badge.add_css_class("warning")
        else:
            self.device_row.set_title(device_name)
            self.device_row.set_subtitle(f"S/N: {serial} • Ready to Scan")
            self.status_badge.set_text("Ready")
            self.status_badge.remove_css_class("warning")
            self.status_badge.remove_css_class("error")
            self.status_badge.add_css_class("success")
