#!/usr/bin/env python3
"""
Main Application Window for Raven Desktop.
Implements modern GTK 4 and Libadwaita styling matching Omarchy.
"""

import os
import subprocess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from ravenscan.hardware import RavenHardware, ScannerStatus, ScanSource
from ravenscan.scanner import ScannerController, ScanOptions
from ravenscan.document import DocumentSession
from ravenscan.pdf_builder import PdfBuilder
from ravenscan.config import ConfigManager
from ravenscan import watchdog
from ravenscan.ui.preview import DocumentPreview
from ravenscan.ui.thumbnails import ThumbnailStrip
from ravenscan.ui.settings_panel import SettingsPanel
from ravenscan.ui.permission_dialog import PermissionDialog

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Raven Desktop")
        self.set_default_size(1120, 780)

        self.hardware = RavenHardware()
        self.controller = ScannerController(self.hardware)
        self.session = DocumentSession()
        self.simulation_mode = False
        self.last_saved_pdf = None

        # Build Main UI Layout
        self._build_ui()

        # Connect session events
        self.session.on_pages_changed = self._on_pages_changed

        watchdog.start()

        # Initial hardware check and periodic polling
        self._poll_hardware()
        GLib.timeout_add_seconds(3, self._poll_hardware)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # 1. HeaderBar
        self.header_bar = Adw.HeaderBar()

        # Scan buttons
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        scan_box.add_css_class("linked")

        # One Scan button; side(s) come from the "Scan Source" setting.
        # (GTK4 set_icon_name() replaces a button's label, which left the old
        # duplex button as an unlabeled icon next to "Scan Single".)
        self.btn_scan_duplex = Gtk.Button()
        self.btn_scan_duplex.set_child(Adw.ButtonContent(icon_name="scanner-symbolic", label="Scan"))
        self.btn_scan_duplex.add_css_class("suggested-action")
        self.btn_scan_duplex.set_tooltip_text("Scan pages in the feeder using the Scan Source setting")
        self.btn_scan_duplex.connect("clicked", lambda b: self._start_scan(None))
        scan_box.append(self.btn_scan_duplex)

        # Kept (hidden) so existing enable/disable code still works.
        self.btn_scan_single = Gtk.Button(label="Scan Single")
        self.btn_scan_single.set_visible(False)
        scan_box.append(self.btn_scan_single)

        self.header_bar.pack_start(scan_box)

        # Right side actions (Save PDF & Save As buttons)
        save_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        save_box.add_css_class("linked")

        self.btn_save_pdf = Gtk.Button(label="Save PDF")
        self.btn_save_pdf.set_icon_name("document-save-symbolic")
        self.btn_save_pdf.add_css_class("accent")
        self.btn_save_pdf.set_tooltip_text("Save PDF directly to destination folder")
        self.btn_save_pdf.set_sensitive(False)
        self.btn_save_pdf.connect("clicked", lambda b: self._on_save_pdf_clicked(save_as=False))
        save_box.append(self.btn_save_pdf)

        self.btn_save_as = Gtk.Button(icon_name="document-save-as-symbolic")
        self.btn_save_as.set_tooltip_text("Save As... (Choose custom location)")
        self.btn_save_as.add_css_class("accent")
        self.btn_save_as.set_sensitive(False)
        self.btn_save_as.connect("clicked", lambda b: self._on_save_pdf_clicked(save_as=True))
        save_box.append(self.btn_save_as)

        self.header_bar.pack_end(save_box)

        self.btn_clear = Gtk.Button(label="Clear")
        self.btn_clear.set_icon_name("edit-clear-all-symbolic")
        self.btn_clear.add_css_class("flat")
        self.btn_clear.set_sensitive(False)
        self.btn_clear.connect("clicked", self._on_clear_clicked)
        self.header_bar.pack_end(self.btn_clear)

        # Menu Button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Setup USB Permissions...", "app.permissions")
        menu.append("Toggle Simulation Mode", "app.toggle_sim")
        menu.append("Open Scans Folder", "app.open_folder")
        menu.append("About Raven Desktop", "app.about")
        menu_button.set_menu_model(menu)
        self.header_bar.pack_end(menu_button)

        main_box.append(self.header_bar)

        # 2. Permission / Status Banner
        self.banner = Adw.Banner()
        self.banner.set_title("Raven Compact Scanner detected, but USB permissions are needed.")
        self.banner.set_button_label("Fix Permissions")
        self.banner.connect("button-clicked", self._on_banner_fix_clicked)
        main_box.append(self.banner)

        # 3. Main Split View (Sidebar + Content)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(380)
        paned.set_hexpand(True)
        paned.set_vexpand(True)

        # Left Notebook (Settings & Thumbnails tabs)
        left_notebook = Gtk.Notebook()
        left_notebook.set_tab_pos(Gtk.PositionType.TOP)

        self.settings_panel = SettingsPanel(self)
        left_notebook.append_page(self.settings_panel, Gtk.Label(label="Settings"))

        self.thumbnail_strip = ThumbnailStrip(self.session, self._on_page_selected)
        left_notebook.append_page(self.thumbnail_strip, Gtk.Label(label="Pages"))

        paned.set_start_child(left_notebook)

        # Right Preview Area
        self.preview = DocumentPreview()
        self.preview.on_rotate_callback = self._on_preview_rotated
        paned.set_end_child(self.preview)

        main_box.append(paned)

        # 4. Bottom Status & Action Bar
        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.bottom_bar.set_margin_top(6)
        self.bottom_bar.set_margin_bottom(6)
        self.bottom_bar.set_margin_start(16)
        self.bottom_bar.set_margin_end(16)

        self.status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.bottom_bar.append(self.status_icon)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_halign(Gtk.Align.START)
        self.bottom_bar.append(self.status_label)

        self.spinner = Gtk.Spinner()
        self.bottom_bar.append(self.spinner)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.bottom_bar.append(spacer)

        self.btn_open_saved = Gtk.Button(label="Open Document")
        self.btn_open_saved.set_icon_name("document-open-symbolic")
        self.btn_open_saved.add_css_class("flat")
        self.btn_open_saved.set_visible(False)
        self.btn_open_saved.connect("clicked", self._on_open_saved_clicked)
        self.bottom_bar.append(self.btn_open_saved)

        self.btn_open_folder = Gtk.Button(label="Open Folder")
        self.btn_open_folder.set_icon_name("folder-symbolic")
        self.btn_open_folder.add_css_class("flat")
        self.btn_open_folder.set_visible(False)
        self.btn_open_folder.connect("clicked", self._on_open_folder_clicked)
        self.bottom_bar.append(self.btn_open_folder)

        main_box.append(self.bottom_bar)

    def _poll_hardware(self) -> bool:
        status, info = self.controller.check_connection()

        is_connected = (status != ScannerStatus.DISCONNECTED)
        is_writable = (status == ScannerStatus.READY)
        name = info.get("name", "Raven Compact WiFi")
        serial = info.get("serial", "")

        self.settings_panel.set_device_status(is_connected, is_writable, name, serial)

        if status == ScannerStatus.PERMISSION_DENIED:
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        # Update Header Subtitle
        if self.simulation_mode:
            self.header_bar.set_title_widget(Adw.WindowTitle(title="Raven Desktop", subtitle="Simulation Mode"))
        elif is_writable:
            self.header_bar.set_title_widget(Adw.WindowTitle(title="Raven Desktop", subtitle=f"{name} • Ready"))
        elif is_connected:
            self.header_bar.set_title_widget(Adw.WindowTitle(title="Raven Desktop", subtitle=f"{name} • USB Permissions Needed"))
        else:
            self.header_bar.set_title_widget(Adw.WindowTitle(title="Raven Desktop", subtitle="Scanner Disconnected"))

        return True

    def _require_doc_name(self) -> bool:
        """Returns True if a document name is set; otherwise tells the user."""
        if self.settings_panel.get_doc_name():
            return True
        dialog = Adw.AlertDialog(
            heading="Document Name Required",
            body="Enter a document name before scanning. It is used as the PDF's file name.",
        )
        dialog.add_response("ok", "OK")
        dialog.connect("response", lambda d, r: self.settings_panel.focus_doc_name())
        dialog.present(self)
        self._update_status("Enter a document name first.")
        return False

    def _start_scan(self, source=None):
        if not self._require_doc_name():
            return
        options = self.settings_panel.get_options()
        if source is not None:
            options.source = source
        self._pages_before_scan = len(self.session.pages)

        self.btn_scan_duplex.set_sensitive(False)
        self.btn_scan_single.set_sensitive(False)
        self.spinner.start()

        def on_status_cb(msg: str):
            GLib.idle_add(self._update_status, msg)

        def on_page_cb(img_path: str, side: str):
            GLib.idle_add(self._add_page_to_session, img_path, side, options.resolution_dpi)

        def on_complete_cb():
            GLib.idle_add(self._on_scan_finished)

        def on_error_cb(err: str):
            GLib.idle_add(self._on_scan_error, err)

        self.controller.start_scan_async(
            options=options,
            on_status=on_status_cb,
            on_page=on_page_cb,
            on_complete=on_complete_cb,
            on_error=on_error_cb,
            simulation=self.simulation_mode,
        )

    def _update_status(self, msg: str):
        self.status_label.set_text(msg)

    def _add_page_to_session(self, img_path: str, side: str, dpi: int):
        # add_scanned_image fires on_pages_changed, which already rebuilds the
        # thumbnail strip and loads the preview; don't do that work twice.
        self.session.add_scanned_image(img_path, side=side, dpi=dpi)

    def _on_scan_finished(self):
        self.spinner.stop()
        self.btn_scan_duplex.set_sensitive(True)
        self.btn_scan_single.set_sensitive(True)
        self._update_status(f"Scan complete. Total pages: {len(self.session.pages)}")
        # Auto-save to the destination folder when the scan added pages.
        if self.session.pages and len(self.session.pages) > getattr(self, "_pages_before_scan", 0):
            self._on_save_pdf_clicked(save_as=False)

    def _on_scan_error(self, err: str):
        self.spinner.stop()
        self.btn_scan_duplex.set_sensitive(True)
        self.btn_scan_single.set_sensitive(True)
        self._update_status(f"Error: {err}")

    def _on_pages_changed(self):
        has_pages = len(self.session.pages) > 0
        can_save = has_pages and not getattr(self, "_saving", False)
        self.btn_save_pdf.set_sensitive(can_save)
        self.btn_save_as.set_sensitive(can_save)
        self.btn_clear.set_sensitive(can_save)
        self.thumbnail_strip.update_pages()
        current_page = self.session.get_selected_page()
        self.preview.display_page(current_page)

    def _on_page_selected(self, index: int):
        if 0 <= index < len(self.session.pages):
            page = self.session.pages[index]
            self.preview.display_page(page)

    def _on_preview_rotated(self, page):
        self.thumbnail_strip.update_pages()

    def _on_clear_clicked(self, button):
        self.session.clear()
        self.btn_open_saved.set_visible(False)
        self.btn_open_folder.set_visible(False)
        self._update_status("Session cleared.")

    def _on_save_pdf_clicked(self, save_as: bool = False):
        if not self.session.pages:
            return

        options = self.settings_panel.get_options()

        if save_as:
            # Open Save File Dialog
            dialog = Gtk.FileDialog()
            dialog.set_title("Save Scanned PDF As...")
            dialog.set_initial_folder(Gio.File.new_for_path(options.save_dir))
            
            default_filename = PdfBuilder.generate_filename(
                base_name=options.document_name,
                append_date=options.append_date,
                extension="pdf",
                directory=options.save_dir
            )
            dialog.set_initial_name(default_filename)

            def on_save_as_finish(dialog_obj, result):
                try:
                    gfile = dialog_obj.save_finish(result)
                    if gfile:
                        path = gfile.get_path()
                        if not path and gfile.get_uri():
                            path, _ = GLib.filename_from_uri(gfile.get_uri())
                        if path:
                            self._execute_save(path, options)
                except Exception:
                    pass

            dialog.save(self, None, on_save_as_finish)
        else:
            if not self._require_doc_name():
                return
            # Direct save to chosen save_dir with document_name. The folder
            # checks touch the rclone Drive mount, so they run in the worker.
            self._execute_save(None, options)

    def _execute_save(self, out_path, options: ScanOptions):
        # Snapshot the pages being saved so only these are removed afterwards,
        # even if another scan adds pages while this save is running.
        pages = list(self.session.pages)
        self._saving = True
        self.btn_save_pdf.set_sensitive(False)
        self.btn_save_as.set_sensitive(False)
        self.btn_clear.set_sensitive(False)
        self.spinner.start()
        self._update_status("Saving...")

        def save_worker():
            try:
                def progress(msg):
                    GLib.idle_add(self._update_status, msg)

                path = out_path
                if path is None:
                    ConfigManager.heal_mount_if_needed(options.save_dir)
                    os.makedirs(options.save_dir, exist_ok=True)
                    filename = PdfBuilder.generate_filename(
                        base_name=options.document_name,
                        append_date=options.append_date,
                        extension="pdf",
                        directory=options.save_dir
                    )
                    path = os.path.join(options.save_dir, filename)

                progress(f"Saving '{os.path.basename(path)}'...")
                PdfBuilder.export_pdf(pages, path, ocr=options.ocr, progress_cb=progress)
                DocumentSession.delete_source_files(pages)

                def on_done():
                    self._saving = False
                    self.spinner.stop()
                    self.last_saved_pdf = path
                    # Saved pages are done: drop them so the next scan starts fresh.
                    self.session.remove_pages(pages)
                    self.settings_panel.clear_doc_name()
                    self.btn_open_saved.set_visible(True)
                    self.btn_open_folder.set_visible(True)
                    self._update_status(f"Saved: {os.path.basename(path)}")

                GLib.idle_add(on_done)
            except Exception as e:
                def on_err():
                    self._saving = False
                    self.spinner.stop()
                    self._on_pages_changed()
                    self._update_status(f"Save failed: {e}")
                GLib.idle_add(on_err)

        import threading
        threading.Thread(target=save_worker, daemon=True).start()

    def _on_open_saved_clicked(self, button):
        if self.last_saved_pdf and os.path.exists(self.last_saved_pdf):
            subprocess.Popen(["xdg-open", self.last_saved_pdf])

    def _on_open_folder_clicked(self, button):
        save_dir = self.settings_panel.save_dir
        if os.path.exists(save_dir):
            subprocess.Popen(["xdg-open", save_dir])

    def _on_banner_fix_clicked(self, banner):
        self.show_permission_dialog()

    def show_permission_dialog(self):
        cmd = self.hardware.get_udev_fix_command()
        dialog = PermissionDialog(self, cmd)
        dialog.present()

    def toggle_simulation_mode(self):
        self.simulation_mode = not self.simulation_mode
        state = "enabled" if self.simulation_mode else "disabled"
        self._update_status(f"Simulation mode {state}.")
        self._poll_hardware()
