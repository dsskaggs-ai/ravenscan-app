#!/usr/bin/env python3
"""
Application entry point for Raven Desktop (RavenScan).
Initializes Adw.Application, registers global actions, and loads stylesheet.
"""

import os
import sys
import subprocess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Gdk

from ravenscan.ui.window import MainWindow
from ravenscan.pdf_builder import DEFAULT_SCAN_DIR, PdfBuilder

CUSTOM_CSS = """
.card {
    border-radius: 12px;
    background-color: alpha(currentColor, 0.04);
}

.dim-label {
    opacity: 0.7;
}

.success {
    color: #4ade80;
}

.warning {
    color: #fbbf24;
}

.error {
    color: #f87171;
}

.accent {
    font-weight: bold;
}
"""

class RavenApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="com.raven.RavenScan",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()
        self._setup_actions()

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CUSTOM_CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _setup_actions(self):
        # Action: Setup Permissions
        act_perm = Gio.SimpleAction.new("permissions", None)
        act_perm.connect("activate", self._on_permissions)
        self.add_action(act_perm)

        # Action: Toggle Simulation
        act_sim = Gio.SimpleAction.new("toggle_sim", None)
        act_sim.connect("activate", self._on_toggle_sim)
        self.add_action(act_sim)

        # Action: Open Scans Folder
        act_folder = Gio.SimpleAction.new("open_folder", None)
        act_folder.connect("activate", self._on_open_folder)
        self.add_action(act_folder)

        # Action: About
        act_about = Gio.SimpleAction.new("about", None)
        act_about.connect("activate", self._on_about)
        self.add_action(act_about)

    def do_activate(self):
        if not self.window:
            self.window = MainWindow(self)
        self.window.present()

    def _on_permissions(self, action, param):
        if self.window:
            self.window.show_permission_dialog()

    def _on_toggle_sim(self, action, param):
        if self.window:
            self.window.toggle_simulation_mode()

    def _on_open_folder(self, action, param):
        if self.window and hasattr(self.window, "settings_panel"):
            out_dir = self.window.settings_panel.save_dir
        else:
            out_dir = PdfBuilder.ensure_default_dir()
        subprocess.Popen(["xdg-open", out_dir])

    def _on_about(self, action, param):
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name="Raven Desktop",
            application_icon="ravenscan",
            version="1.0.0",
            developer_name="Omarchy Community",
            comments="Native Linux document scanning software tailored for Raven Compact Scanner (Avision AD215W) and compatible scanners.",
            website="https://github.com/cbrooker/Raven-Scanner-Wiki",
            issue_url="https://github.com/cbrooker/Raven-Scanner-Wiki/issues",
            copyright="© 2026 Raven Community / Omarchy",
            license_type=Gtk.License.MIT_X11,
        )
        about.present()

def main():
    app = RavenApp()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main())
