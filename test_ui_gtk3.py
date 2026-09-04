#!/usr/bin/env python3
"""Tests de la UI GTK3 (usa display real; skip si no hay)."""
import os
import tempfile
import unittest
from pathlib import Path

HAVE_GTK3 = False
SKIP_REASON = 'GTK3 (gi) no disponible'
try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gio, GLib, Gtk  # noqa: F401
    HAVE_GTK3 = True
except ValueError as e:
    SKIP_REASON = f'Gtk 4 ya cargado en este proceso; ejecuta test_ui_gtk3 por separado ({e})'
except Exception as e:
    SKIP_REASON = f'GTK3 (gi) no disponible: {e}'

HAVE_DISPLAY = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

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
        'if [[ "$1" == "-s" ]]; then shift 2; fi\n'
        'case "$1" in\n'
        '  devices) echo "List of devices attached"; echo "R5CX905SJQD            device usb:1-1 product:e3q model:SM_S928B";;\n'
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
        '      cmd) shift; [[ "$1" == "role" ]] && echo "com.sec.android.app.launcher";;\n'
        '      pm) shift; [[ "$1" == "list" ]] && echo "package:com.a.b";;\n'
        '    esac;;\n'
        '  *) echo ok;;\nesac\n')
    path.chmod(0o755)


FAKE_ADB = Path(TMP) / 'fake-adb'
_fake_adb(FAKE_ADB)
os.environ['GEKKO_ADB_EXECUTABLE'] = str(FAKE_ADB)


def _pump(ms=300):
    end = GLib.get_monotonic_time() + ms * 1000
    ctx = GLib.MainContext.default()
    while GLib.get_monotonic_time() < end:
        while ctx.pending():
            ctx.iteration(False)
        GLib.usleep(10000)


@unittest.skipUnless(HAVE_GTK3, SKIP_REASON)
@unittest.skipUnless(HAVE_DISPLAY, 'Sin display')
class TestGtk3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        import gekko_adb_core as core
        cls.core = core
        cls._old_adb = core.ADB_EXEC
        core.ADB_EXEC = str(FAKE_ADB)
        cls.mod = importlib.import_module('gekko-adb-gtk3')
        cls.app = cls.mod.GekkoAdbGtk3App()
        cls.app.set_flags(cls.app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register()

    @classmethod
    def tearDownClass(cls):
        cls.core.ADB_EXEC = cls._old_adb

    def _activate(self):
        app = self.app
        if app.win is None or not app.win.get_visible():
            app.win = None
            app.activate()
        return app

    def test_build_ui_y_catalogo(self):
        app = self._activate()
        pages = app._stack.get_children()
        self.assertEqual(len(pages), len(app._catalogo['categorias']))
        self.assertIsNotNone(app._conn_pill_label)

    def test_refresh_device(self):
        app = self._activate()
        app._refreshing = False
        app._refresh_device()
        for _ in range(40):
            _pump(100)
            if app._dashboard_widgets['model'].get_text() != '…':
                break
        cap = {k: w.get_text() for k, w in app._dashboard_widgets.items()}
        self.assertEqual(cap.get('model'), 'SAMSUNG SM-S928B')
        self.assertEqual(cap.get('android'), 'Android 16 (API 36) [arm64-v8a]')
        self.assertEqual(cap.get('battery'), '27% | 27 °C | 4.2 V (Bien)')
        self.assertEqual(cap.get('secure'), 'Knox 0x1 (Tripped)')
        self.assertEqual(cap.get('display'), '1440x3120 @ 600')
        self.assertEqual(cap.get('nav_mode'), 'Gestos')
        self.assertEqual(cap.get('home_role'), 'com.sec.android.app.launcher')
        self.assertIn('R5CX905SJQD', app._conn_pill_label.get_text())

    def test_confirmar_ejecuta_una_vez(self):
        app = self._activate()
        launched = []
        confirms = []
        orig_confirm = app._confirm_dialog
        app._launch = lambda spec, valores=None, flags=None: launched.append(spec['id'])

        def spy_confirm(spec, valores, flags):
            confirms.append(spec['id'])
            return orig_confirm(spec, valores, flags)
        app._confirm_dialog = spy_confirm
        try:
            spec = {'id': 'reboot', 'titulo': 'Reiniciar', 'desc': 'adb reboot', 'accion': 'reboot',
                    'args': {'mode': 'normal'}, 'peligro': True, 'confirmar': True}
            app._on_command(None, spec)
            _pump(100)
            dialog = None
            for w in Gtk.Window.list_toplevels():
                if isinstance(w, Gtk.Dialog) and (w.get_title() or '').startswith('¿Confirmar'):
                    dialog = w
            self.assertIsNotNone(dialog)
            dialog.response(Gtk.ResponseType.OK)
            _pump(200)
            self.assertEqual(launched, ['reboot'])
            self.assertEqual(confirms, ['reboot'])
        finally:
            del app._launch
            app._confirm_dialog = orig_confirm

    def test_campos_dialog_valida(self):
        app = self._activate()
        got = []
        app._run_spec = lambda spec, valores=None, flags=None: got.append((valores, flags))
        try:
            spec = next(c for k in app._catalogo['categorias'] for c in k['comandos'] if c['id'] == 'tap')
            dialog = app._campos_dialog(spec)
            grid = dialog.get_content_area().get_children()[0]
            entry_x = grid.get_child_at(1, 0)
            entry_x.set_text('abc')
            dialog.response(Gtk.ResponseType.OK)
            _pump(100)
            self.assertEqual(got, [])
            entry_x.set_text('10')
            dialog.response(Gtk.ResponseType.OK)
            _pump(100)
            self.assertEqual(got[0][0], {'x': '10', 'y': '1200'})
        finally:
            del app._run_spec

    def test_selector_archivos_no_usa_run(self):
        """FileChooserNative.run() con show() previo aborta; se usa show + response."""
        app = self._activate()
        entry = Gtk.Entry()
        created = []
        orig = Gtk.FileChooserNative

        class Spy(orig):
            def __init__(self, **kw):
                super().__init__(**kw)
                created.append(self)

            def show(self):
                self.shown = True

            def run(self):
                raise AssertionError('run() no debe usarse')
        self.mod.Gtk.FileChooserNative = Spy
        try:
            app._on_file_pick(None, entry, 'archivo', 'apk', app.win)
            self.assertEqual(len(created), 1)
            self.assertTrue(getattr(created[0], 'shown', False))
            self.assertIn(created[0], app._native_dialogs)
        finally:
            self.mod.Gtk.FileChooserNative = orig


if __name__ == '__main__':
    unittest.main()
