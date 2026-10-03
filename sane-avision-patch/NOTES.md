# Raven Compact WiFi Scanner — SANE avision Backend Investigation

**Status as of 2026-09-24 evening: PAUSED, real progress made, not complete.**

## TL;DR for whoever picks this up

We got a real 60KB stripe of actual scanned image data through SANE for the
first time ever tonight. The scanner mechanically works fine (confirmed via
successful scan on a Mac's native ICA driver). The blocker is **not**
hardware, cable, power, or SANE recognizing the device — it's that this
specific USB unit silently disconnects and re-enumerates on the Linux USB bus
every ~20-25 seconds (its own internal timer, confirmed via
`POWER_SAVING_TIMER` capability flag in its own INQUIRY response), and a
single 150dpi scan needs ~110 stripe reads to complete — far more read cycles
than fit in one ~20s live window.

**Next step (not yet attempted):** either (A) make the SANE avision backend
detect a genuine USB disconnect mid-scan and transparently reopen the device
handle + resume from where it left off, or (B) find and write the NVRAM
field that disables this device's power-saving timer entirely (its
capability table advertises NVRAM read/write support), which would remove
the need for any reconnect logic at all. Try (B) first — much lower risk,
and if it works, it's a total fix instead of a workaround.

## Hardware facts (all confirmed, not guesses)

- Device: Raven Compact WiFi, USB `0638:3200`, rebadged Avision AD215W,
  firmware rev 6.07.
- **Self-powered** (`bmAttributes = 0xc0`), not USB bus-powered — ruled out
  power starvation from hub/cable/port entirely. Its own external adapter
  is plugged in with the indicator light on.
- Confirmed working scan via Image Capture.app on macOS using the
  vendor's native arm64 ICA driver — proves the scanner unit itself, its
  power supply, and cable are all fine. The problem is Linux-side only.
- Disconnect/reconnect happens on a near-exact ~20-25s cadence, confirmed
  repeatedly in `journalctl -k`, independent of whether anything is
  actively communicating with the device (it does this even sitting idle).
  Kernel log signature:
  ```
  usb 1-8.3: USB disconnect, device number N
  usb 1-8-port3: Cannot enable. Maybe the USB cable is bad?   <- red herring, ignore
  usb 1-8-port3: attempt power cycle
  usb 1-8.3: new high-speed USB device number N+2 using xhci_hcd
  usb 1-8.3: New USB device found, idVendor=0638, idProduct=3200 ...
  ```
- INQUIRY response capability table includes (from `attach:` debug log):
  `ESA1: BUTTON_CONTROL SW_CALIB NEED_SW_GAMMA XYRES_DIFFERENT`
  `ESA2: EXPOSURE_CTRL SUPPORTS_QUALITY_SPEED_CAL HAS_PUSH_BUTTON NEW_CAL_METHOD_3x3_MATRIX`
  `ESA3: GRAY_WHITE SUPPORTS_GAIN_CONTROL 3x3COL_TABLE POWER_SAVING_TIMER NVM_DATA_REC`
  `ESA4: SUPPORTS_ACCESSORIES_DETECT SUPPORTS_ASIC_UPDATE SUPPORTS_LIGHT_DETECT`
  `ESA6: SUPPORTS_PAPER_LENGTH_SETTING SUPPORTS_GET_BACKGROUND_RASTER SUPPORTS_NVRAM_RESET`

  The `POWER_SAVING_TIMER` and `NVM_DATA_REC`/`SUPPORTS_NVRAM_RESET` flags
  are the interesting ones for path (B) above.

- Not a whitelist/recognition issue in the sense we originally thought — the
  original "not yet in whitelist!" rejection was real but is now fixed (see
  below). The remaining problem is purely about surviving mid-scan
  disconnects.

## Patches applied (all in `sane-avision-patch/avision.c.patched` in this dir)

Built from vanilla upstream SANE 1.4.0 source
(`https://deb.debian.org/debian/pool/main/s/sane-backends/sane-backends_1.4.0.orig.tar.bz2`
— gitlab.com was down/503 all evening, use the Debian mirror).

1. **Whitelist entry** (recovered from the original Sep 20 session's Arch
   PKGBUILD, found via `.claude/file-history`): adds a device-table entry
   for `0x0638, 0x3200` mapped to the generic Avision `AD215W` profile, right
   after the existing `0x0638, 0x0A27` (AV120) entry in the model table.
   Without this, `scanimage -L` reports `"Raven" - "Compact_WiFi" not yet in
   whitelist!` and refuses to attach at all. This part was already working
   before tonight (installed as a custom-rebuilt Arch package,
   `sane 1.4.0-5`, `Validated By: None`).

2. **`wait_ready()` fast-retry rewrite**: was 10 tries, 15s timeout each,
   1s sleep between (worst case ~160s per attempt sequence, way longer
   than the ~20s device reset cycle — guaranteed to miss every live
   window). Now: 60 tries, 2s timeout, 300ms sleep between. This alone was
   enough to get past `TEST_UNIT_READY` reliably.

3. **`STD_TIMEOUT`/`STD_STATUS_TIMEOUT` global shrink**: 30000ms/10000ms →
   5000ms/3000ms, `retry` 4 → 40. Same rationale — every command's
   worst-case wait time needs to be well under the ~20s device cycle.

4. **`AVISION_SCSI_READ` timeout carve-out**: the global shrink above broke
   actual image-data stripe reads (they legitimately need more than 5s —
   physically moving the scan head/CCD). Added a specific case:
   write/read 8000ms, status 5000ms — longer than tiny status commands,
   still short of the ~20s device cycle.

5. **Retry-loop bypass bug fix** (the most important one): in `avision_cmd`,
   when the initial command write failed AND the subsequent
   "clear the FIFO" status read (`avision_usb_status`) also failed, the
   code did a hard `return SANE_STATUS_IO_ERROR` — completely skipping
   the outer retry loop and its remaining budget. Changed to `goto
   write_usb_cmd` like the other failure branches, so it actually retries
   instead of giving up on the first double-failure.

6. **`get_accessories_info()` failure made non-fatal**: this device's
   INQUIRY claims `SUPPORTS_ACCESSORIES_DETECT`, but the actual
   accessories-detect READ command never completes reliably on this unit.
   `additional_probe()` used to treat any failure here as fatal to the
   whole `sane_open()`. Now it logs and continues with defaults — this is
   what got us from "can't even open the device" to "opens fine, gets
   real scan data."

All patches are marked with `HERMES PATCH:` comments in the source for
easy `grep`.

## Result after all patches

- `sane_open()` succeeds reliably now (previously failed ~100% of the time).
- `set_window()` (telling the scanner the scan parameters) succeeds.
- `normal_calibration()` runs, device reports "no calibration needed."
- `sane_start()` launches the reader thread successfully.
- **First stripe of real image data (60,672 bytes) reads successfully.**
- Second stripe read fails because the device disconnects mid-read
  (confirmed via exact kernel-log timestamp match with the failure).
  `reader_process` correctly detects this, cleans up, and returns —
  no crash, no corrupted output, it just can't get more than ~1 stripe
  per live window.

## What's needed to actually finish this

A full 150dpi scan needs roughly 110 stripe reads (`reader_process: total_size:
6647376` bytes / ~60KB per stripe). At best one stripe survives per ~20s
live window, so a naive "just retry forever" approach would need the
driver to survive ~100+ disconnect/reconnect cycles per scan, and SANE's
USB device handle (bus:dev path) is invalidated by each reconnect — the
current code has no mechanism to detect "this failure means the device
really vanished and got a new bus address" vs. "this is a transient stall
on a still-live connection," nor any logic to reopen a fresh handle and
resume a scan already in progress.

**Recommended next step: try to find and disable the power-saving timer via
NVRAM first (Option B from tonight's conversation).** The device's own
capability flags advertise NVRAM read/write and a reset command. If there's
a byte in its NVRAM layout that governs the power-timer interval or
disables it, writing that once would make this whole problem disappear —
no reconnect logic ever needed. Look at `avision.c`'s existing
`AVReadNVMData`/`AVWriteNVMData`-equivalent functions (search for
`nvram` in the source) as a starting point; the layout itself is unknown
and would need to be reverse-engineered or found in Avision's other model
documentation/source if it exists publicly.

**Fallback: build real reconnect-and-resume support.** This means, at
minimum:
- Detecting "handle is dead because of a real USB disconnect" specifically
  (distinct from a stalled-but-still-live handle) — probably by having
  `sanei_usb_read_bulk`/`write_bulk` failures trigger a poll of whether the
  original `bus:dev` path still exists, vs. whether a device with the same
  VID:PID has reappeared at a *new* bus:dev path.
- Closing the stale handle and reopening a fresh one at the new path.
- Resuming the reader_process's in-flight state (partial stripe buffers,
  deinterlacing state, output file position) without corrupting the image
  — this is the risky part, since `reader_process` holds a lot of
  scan-in-progress state that doesn't currently have any serialize/resume
  path.

This is real engineering effort (multi-hour, non-trivial risk of subtle
data corruption bugs), which is why we stopped here instead of pushing
through it at the end of a long day.

## How to pick this back up

1. The patched source is at
   `sane-avision-patch/avision.c.patched` in this directory (fully
   patched, all 6 fixes above already applied) and also still at
   `/tmp/sane-build/backends-1.4.0/backend/avision.c` on OmarchyMBP
   (`/tmp` will not survive a reboot — copy it out if picking this up
   after a reboot).
2. The currently-installed system library
   (`/usr/lib/sane/libsane-avision.so.1.4.0`) already has all 6 patches
   baked in and is what was tested tonight. A backup of the *original*
   upstream-plus-whitelist-only build (before tonight's session) is at
   `sane-avision-patch/libsane-avision.so.1.4.0.upstream-plus-whitelist.orig-backup`
   in this dir, in case a rollback is ever needed.
3. To rebuild after further edits:
   ```bash
   cd /tmp/sane-build/backends-1.4.0   # or wherever the source tree lives
   rm -f backend/libavision_la-avision.lo backend/libavision.la backend/libsane-avision.la
   rm -f backend/.libs/libsane-avision.so*
   make -C backend libsane-avision.la
   sudo cp backend/.libs/libsane-avision.so.1.4.0 /usr/lib/sane/libsane-avision.so.1.4.0
   ```
4. Test with:
   ```bash
   SANE_DEBUG_AVISION=15 timeout 300 scanimage -d avision --format=png \
     --resolution 150 --mode Color -o /tmp/raven_test.png
   ```
   Watch for `colord-sane` racing for the USB device — if present, either
   `systemctl mask colord.service` or accept the occasional collision.
   `colord.service` was left masked on this machine as of tonight; check
   `systemctl status colord.service` before assuming it's still off.
5. Cross-reference kernel disconnect timestamps with SANE debug log
   timestamps (`journalctl -k --since "<time>" | grep -iE "0638|1-8|disconnect"`)
   to confirm whether a given failure is a real bus disconnect or something
   else — don't assume, verify every time, the device's behavior has been
   inconsistent enough that assumptions burned real time tonight.

## Dead ends already ruled out (don't retry these)

- USB hub power starvation — ruled out, self-powered device, tested on
  hub and on a direct host port with identical failure pattern.
- Bad USB cable — kernel warns "maybe bad cable" but this is a red
  herring; the actual cause is the device's own reconnect behavior, not
  cable signal integrity.
- Shipping lock/physical obstruction — ruled out, user confirmed this
  exact unit has scanned reliably in the same spot for years.
- Windows official driver via Wine — segfaults inside Wine's USB
  translation layer partway through real hardware I/O; can't debug a
  Windows PE binary's internals from Linux tooling. Not worth revisiting
  unless a real Windows machine becomes available.
- Wireshark USB capture on macOS — blocked by `DevToolsSecurity`/
  `_developer` group setup not taking effect even after following the
  documented steps + reboot; abandoned in favor of just fixing the SANE
  backend directly, which worked better anyway.

## 2026-09-27 UPDATE: FIRST REAL SCAN WORKS

Last night's "60KB of real data" was wrong: that read returned 0 bytes.
The real root cause was different:

1. **Wrong scanner type.** Inquiry byte [62] is blank, so SANE treated this
   feeder-only unit as a flatbed and requested flatbed ("Normal") scans. The
   device never answered, the host stalled, and the device reset off the
   bus. The ~25s disconnects were caused by those stuck requests, not by an
   idle timer. It stays connected while idle; the only other power-off is
   an auto-off after 4 hours.
   Fix: force AV_SHEETFEED for 0638:3200 (source is now "ADF Front").
2. **Accessory probe.** Forced inquiry_detect_accessories = 0 for 0638:3200.
3. **Retry loop on a status byte.** A single 0x02 byte in the data phase
   (CHECK CONDITION) was resent forever. It now goes to REQUEST SENSE.

Result: open takes ~12s, a full legal page scanned at 150dpi Gray
(1264x2096), and there were ZERO USB disconnects.

Open issues:
- Image shows ghosting/double text in parts. Likely a line-interlace
  quirk (try AV_2ND_LINE_INTERLACED / AV_NO_LINE_DIFFERENCE flags on the
  model entry) or a front/back duplex interleave.
- PNG writer aborted at EOF, which truncated the output. Use --format=pnm
  or tiff instead.
- Not installed system-wide yet. Test with:
  LD_LIBRARY_PATH=/tmp/sanelib scanimage -d avision ...
  To install: sudo cp libsane-avision.so.1.4.0.built-2026-09-27 /usr/lib/sane/libsane-avision.so.1.4.0

## 2026-09-27 later: ghosting = both sides in one image
The scanner always scans both sides, but the inquiry duplex bits are blank.
SANE was reading front and back as a single page, so the two sides were
overlaid (spotted during testing). Splitting rows/columns after the fact did not
work, so the fix has to be in the driver.
Patch: force inquiry_duplex=1 and inquiry_duplex_interlaced=1 for 0638:3200.
"ADF Duplex" is now offered.
Two builds are saved here, and it is not yet known which deinterlace mode
is correct:
 - libsane-avision.so.duplex-stripe (default STRIPE deinterlace)
 - libsane-avision.so.duplex-line   (model flag AV_2ND_LINE_INTERLACED)
Test: LD_LIBRARY_PATH=<dir with libsane-avision.so.1> scanimage -d avision \
  --source "ADF Duplex" --batch=/tmp/p%d.pnm --format=pnm
(PNG output aborted at EOF, so use pnm.)

## 2026-09-27 duplex test 1 (stripe build)
The "ADF Duplex" scan with libsane-avision.so.duplex-stripe produced 2 separate
pages (/tmp/dx_stripe_1.pnm front, dx_stripe_2.pnm back), with no USB
disconnects. Both images still show faint text from the other side.
Pixel correlation between front and back is low in every orientation (same
0.08, mirrored -0.02, flipped 0.04), so it is not yet clear whether this is
deinterlace mixing or physical bleed-through from thin paper.
The scanner also returned a spurious 3rd page (I/O error once the feeder was
empty), which is harmless.
NEXT: reload the page and scan with libsane-avision.so.duplex-line. Compare
the two. If both look the same, treat it as paper bleed-through and fix it
with background whitening.

## 2026-09-27 17:30: duplex results + likely cause of ghosting
- The stripe build is correct for duplex: page 1 = front, page 2 = back, no disconnects.
  The line build (AV_2ND_LINE_INTERLACED) gave the front twice, so it is wrong. Drop it.
- The ghost is NOT paper bleed-through. The faint copy reads normally (not mirrored)
  and is offset vertically. Rows correlate strongly every 3 lines (0.83 at dy=3).
- Keeping every 3rd row gives CLEAN text with no ghost, but only ~4.6in of the page.
- Hypothesis: the scanner ignores --mode Gray and sends COLOR as line-interleaved
  R,G,B rows (inquiry [36] says "3-pass color RGB color plane"). SANE treats each
  row as a separate gray line, so the image has 3x the rows, offset planes stack
  into a ghost, and only the top third of the page fits the byte budget.
- NEXT: scan in --mode Color with the stripe build. If that's still wrong, add
  per-model handling that treats Gray as line-interleaved RGB and keeps one plane.

## 2026-09-27 evening: WORKING
- 300 dpi Color ADF Duplex: 4/4 runs clean front + back (the installed system lib passed too).
  150 dpi feeds too fast and corrupts the rear sensor's color data ~60% of the time
  (horizontal shifts of ~30px appear in one channel partway down the page).
  --speed is accepted but ignored. Resolution is the only thing that slows the feed.
- RavenScan scanner.py: scans at >=300 dpi and downscales afterwards, uses PNM output
  (the PNG writer aborts), keeps pages in ~/.cache/ravenscan/pages (the old code deleted
  the temp dir before the UI copied the pages), fixed the missing Tuple/glob imports
  (the module crashed on import), and shows the real error text.
  Backup: ravenscan/scanner.py.bak-2026-09-27
- Bug: after the last sheet, the backend hit "ADF chute empty" in reader_process and
  returned without closing the pipe, so scanimage hung forever on the next page.
  Fixed with fclose(fp) on the reserve_unit/start_scan/accel-table error paths.
  Build: libsane-avision.so.1.4.0.built-2026-09-27-eof (NOT yet installed, and not yet
  verified on a real multi-sheet run).
- Installed /usr/lib/sane lib = the RAVEN_STRIPE build (md5 c94aecc3...), which works except for
  the end-of-batch hang.
- VERIFIED 18:05: the end-of-batch fix works on a real sheet. The duplex scan finishes in 10.6s total,
  exit 0, clean front + back, and it stops cleanly on "feeder out of documents". This is the build to install.
- 18:09: the sheet stopped partway out of the exit rollers. object_position(REJECT_PAPER) is
  rejected by this unit. release_unit(s, 1) ("release paper", which upstream only sends on cancel)
  after each sheet ejects it fully. Confirmed in testing.
- FINAL build = libsane-avision.so.1.4.0.FINAL-2026-09-27 (all patches: sheetfed, no accessory
  probe, CHECK CONDITION->sense, duplex, EOF pipe close, eject). Install to
  /usr/lib/sane/libsane-avision.so.1.4.0. Use 300 dpi, Color, ADF Duplex.

## 2026-09-27 app fixes (RavenScan UI)
- window.py: one "Scan" button that follows the Scan Source setting (the old duplex button had
  lost its label: GTK4 set_icon_name replaces the label). Auto-saves the PDF to save_dir after each scan.
- pdf_builder.py: OCR path converts pages to JPEG q80 before tesseract. A 2-page legal duplex went
  from 32 MB to 2.8 MB with identical searchable text (159 lines). Looks the same zoomed in.
- Backups: *.bak-2026-09-27 next to each edited file.
