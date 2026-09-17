#!/usr/bin/env python3
"""
Hardware abstraction layer for Raven Compact Scanner (Avision AD215W / AD215).
Supports direct USB Bulk communication via libusb-1.0 and SANE backend fallback.
"""

import os
import sys
import time
import glob
import ctypes
import struct
import subprocess
from enum import Enum
from typing import Optional, Dict, Any, Tuple, List

# USB Vendor and Product IDs for Raven / Avision models
RAVEN_VID = 0x0638

RAVEN_PIDS = {
    0x3200: "Raven Compact WiFi (Avision AD215W)",
    0x2FFF: "Raven Compact USB (Avision AD215)",
    0x2FCA: "Raven Standard WiFi",
    0x2FEC: "Raven Standard USB",
    0x2F4A: "Raven Pro 360W",
    0x2D74: "Raven Pro Original",
    0x2FC9: "Raven Original",
    0x321B: "Raven Pro Max",
    0x321A: "Raven Go Series",
}

class ScannerStatus(Enum):
    DISCONNECTED = "disconnected"
    PERMISSION_DENIED = "permission_denied"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"

class ColorMode(Enum):
    COLOR = "color"
    GRAYSCALE = "grayscale"
    LINEART = "lineart"

class ScanSource(Enum):
    ADF_SIMPLEX = "adf_simplex"
    ADF_DUPLEX = "adf_duplex"
    CARD_SLOT = "card_slot"

class PaperSize(Enum):
    AUTO = ("Auto-detect", 0, 0)
    LETTER = ("US Letter (8.5 x 11 in)", 8.5, 11.0)
    LEGAL = ("US Legal (8.5 x 14 in)", 8.5, 14.0)
    A4 = ("A4 (210 x 297 mm)", 8.27, 11.69)
    BUSINESS_CARD = ("Card (3.5 x 2 in)", 3.5, 2.0)

    def __init__(self, display_name, width_in, height_in):
        self.display_name = display_name
        self.width_in = width_in
        self.height_in = height_in

class DeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16),
        ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8),
        ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8),
        ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16),
        ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8),
        ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8),
        ("bNumConfigurations", ctypes.c_uint8),
    ]

class RavenHardware:
    def __init__(self):
        self.status = ScannerStatus.DISCONNECTED
        self.device_info: Dict[str, Any] = {}
        self.libusb = None
        self.ctx = None
        self._init_libusb()

    def _init_libusb(self):
        try:
            self.libusb = ctypes.CDLL("libusb-1.0.so.0")
            self.libusb.libusb_init.argtypes = [ctypes.c_void_p]
            self.libusb.libusb_init.restype = ctypes.c_int
            self.ctx = ctypes.c_void_p()
            self.libusb.libusb_init(ctypes.byref(self.ctx))
        except Exception as e:
            print(f"[RavenHW] Error initializing libusb: {e}")
            self.libusb = None

    def scan_usb_bus(self) -> Tuple[ScannerStatus, Dict[str, Any]]:
        """
        Inspects the USB bus for Raven / Avision scanner hardware and verifies permissions.
        """
        info = {
            "vid": None,
            "pid": None,
            "name": "Unknown",
            "bus": None,
            "device": None,
            "devnode": None,
            "serial": "Unknown",
            "writable": False,
        }

        # Check sysfs first for quick device identification without needing root
        found = False
        for dev_path in glob.glob("/sys/bus/usb/devices/*"):
            try:
                vid_file = os.path.join(dev_path, "idVendor")
                pid_file = os.path.join(dev_path, "idProduct")
                if os.path.exists(vid_file) and os.path.exists(pid_file):
                    with open(vid_file, "r") as f:
                        vid = int(f.read().strip(), 16)
                    with open(pid_file, "r") as f:
                        pid = int(f.read().strip(), 16)

                    if vid == RAVEN_VID and pid in RAVEN_PIDS:
                        info["vid"] = vid
                        info["pid"] = pid
                        info["name"] = RAVEN_PIDS[pid]

                        bus_file = os.path.join(dev_path, "busnum")
                        devnum_file = os.path.join(dev_path, "devnum")
                        serial_file = os.path.join(dev_path, "serial")

                        if os.path.exists(bus_file):
                            with open(bus_file, "r") as f:
                                info["bus"] = int(f.read().strip())
                        if os.path.exists(devnum_file):
                            with open(devnum_file, "r") as f:
                                info["device"] = int(f.read().strip())
                        if os.path.exists(serial_file):
                            with open(serial_file, "r") as f:
                                info["serial"] = f.read().strip()

                        if info["bus"] is not None and info["device"] is not None:
                            devnode = f"/dev/bus/usb/{info['bus']:03d}/{info['device']:03d}"
                            info["devnode"] = devnode
                            info["writable"] = os.access(devnode, os.R_OK | os.W_OK)

                        found = True
                        break
            except Exception:
                continue

        if not found:
            self.status = ScannerStatus.DISCONNECTED
            self.device_info = {}
            return self.status, {}

        self.device_info = info
        if not info["writable"]:
            self.status = ScannerStatus.PERMISSION_DENIED
        else:
            self.status = ScannerStatus.READY

        return self.status, self.device_info

    def get_udev_fix_command(self) -> str:
        """Returns the terminal command the user can execute to grant scanner permissions."""
        return (
            'echo \'SUBSYSTEM=="usb", ATTR{idVendor}=="0638", ATTR{idProduct}=="3200", '
            'MODE="0666", GROUP="scanner", TAG+="uaccess"\' | sudo tee /etc/udev/rules.d/99-raven-scanner.rules '
            '&& sudo udevadm control --reload-rules && sudo udevadm trigger'
        )

    def close(self):
        if self.libusb and self.ctx:
            try:
                self.libusb.libusb_exit(self.ctx)
            except Exception:
                pass
            self.ctx = None
