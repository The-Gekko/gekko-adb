#!/usr/bin/env python3
"""Tests de la UI GTK3 (usa display real; skip si no hay)."""
import os
import tempfile
import unittest
from pathlib import Path

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gio, GLib, Gtk  # noqa: F401
    HAVE_GTK3 = True
except Exception:
    HAVE_GTK3 = False

if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
    HAVE_DISPLAY = True
else:
    HAVE_DISPLAY = False

TMP = tempfile.mkdtemp(prefix='gekko_ui3_test_')
HOME_FAKE = Path(TMP) / 'home'
HOME_FAKE.mkdir()
os.environ['HOME'] = str(HOME_FAKE)
os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
os.environ['XDG_STATE_HOME'] = str(HOME_FAKE / 'state')
os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
os.environ['GEKKO_ADB_BASE'] = str(Path(__file__).resolve().parent)
os.environ['GEKKO_SCRCPY_EXECUTABLE'] = '/bin/true'


def _fake_adb(path):
    path.write_text(
        '#!/bin/bash\n'
        'case "$1" in\n'
        '  devices) echo -e "List of devices attached\\nR5CX905SJQD\\tdevice";;\n'
        '  shell) shift\n'
        '    case "$1" in\n'
        '      getprop) shift\n'
        '        case "$1" in\n'
        '          ro.product.model) echo "SM-S928B";;\n'
        '          ro.product.brand) echo samsung;;\n'
        '          ro.build.version.release) echo 16;;\n'
        '          ro.build.version.sdk) echo 36;;\n'
        '          ro.product.cpu.abi) echo arm64-v8a;;\n'
        '          ro.boot.warranty_bit) echo 1;;\n'
        '        esac;;\n'
        '      dumpsys) shift; [[ "$1" == "battery" ]] && echo -e "Current Battery Service state:\\n  status: 2\\n  health: 2\\n  present: true\\n  level: 27\\n  scale: 100\\n  voltage: 4200\\n  temperature: 270";;\n'
        '      wm) shift; [[ "$1" == "size" ]] && echo "Physical size: 1440x3120"; [[ "$1" == "density" ]] && echo "Physical density: 600";;\n'
        '      settings) shift; [[ "$1" == "get" && "$3" == "navigation_mode" ]] && echo 2;;\n'
        '      cmd) shift; [[ "$1" == "role" ]] && shift && echo "com.sec.android.app.launcher";;\n'
        '    esac;;\n'
        '  *) echo ok;;\nesac\n')
    path.chmod(0o755)


FAKE_ADB = Path(TMP) / 'fake-adb'
_fake_adb(FAKE_ADB)
os.environ['GEKKO_ADB_EXECUTABLE'] = str(FAKE_ADB)


@unittest.skipUnless(HAVE_GTK3, 'GTK3 (gi) no disponible')
@unittest.skipUnless(HAVE_DISPLAY, 'Sin display')
class TestGtk3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        import gekko_adb_core as core
        core.ADB_EXEC = str(FAKE_ADB)
        m = importlib.import_module('gekko-adb-gtk3')
        cls.mod = m
        cls.app = m.GekkoAdbGtk3App()
        cls.app.set_flags(cls.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register()

    def _run_until_model(self, app, ms=4000):
        import time
        captured = {}
        deadline = time.time() + ms / 1000
        loop = GLib.MainLoop()

        def probe():
            text = app._dashboard_widgets['model'].get_text()
            if text != '…' or time.time() > deadline:
                captured.update({k: w.get_text()
                               for k, w in app._dashboard_widgets.items()})
                app.win.destroy()
                loop.quit()
                return False
            return True

        app.activate()
        GLib.timeout_add(120, probe)
        loop.run()
        return captured

    def test_build_ui_y_catalogo(self):
        app = self.app
        app.activate()
        pages = app._stack.get_children()
        n_cat = len(app._catalogo['categorias'])
        self.assertEqual(len(pages), n_cat)
        self.assertIsNotNone(app._conn_pill_label)
        app.win.destroy()

    def test_refresh_device(self):
        cap = self._run_until_model(self.app)
        self.assertEqual(cap.get('model'), 'SAMSUNG SM-S928B')
        self.assertEqual(cap.get('android'), 'Android 16 (API 36) [arm64-v8a]')
        self.assertEqual(cap.get('battery'), '27% | 27 °C | 4.2 V (Bien)')
        self.assertEqual(cap.get('secure'), 'Knox 0x1 (Tripped)')
        self.assertEqual(cap.get('display'), '1440x3120 @ 600')
        self.assertEqual(cap.get('nav_mode'), 'Gestos')
        self.assertEqual(cap.get('home_role'), 'com.sec.android.app.launcher')


if __name__ == '__main__':
    unittest.main()
