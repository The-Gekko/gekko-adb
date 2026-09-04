#!/usr/bin/env python3
"""Tests de la UI GTK4 (usa display real; skip si no hay).

GTK 3 y GTK 4 no coexisten en un proceso: este módulo se ejecuta aparte
(`python3 -m unittest test_ui_gtk4`).
"""
import os
import tempfile
import unittest
from pathlib import Path

HAVE_GTK4 = False
SKIP_REASON = 'GTK4 (gi) no disponible'
try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gio, GLib, Gtk  # noqa: F401
    HAVE_GTK4 = True
except ValueError as e:
    SKIP_REASON = f'Gtk 3 ya cargado en este proceso; ejecuta test_ui_gtk4 por separado ({e})'
except Exception as e:
    SKIP_REASON = f'GTK4 (gi) no disponible: {e}'

HAVE_DISPLAY = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

TMP = tempfile.mkdtemp(prefix='gekko_ui4_test_')
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


@unittest.skipUnless(HAVE_GTK4, SKIP_REASON)
@unittest.skipUnless(HAVE_DISPLAY, 'Sin display')
class TestGtk4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        import gekko_adb_core as core
        cls.core = core
        cls._old_adb = core.ADB_EXEC
        core.ADB_EXEC = str(FAKE_ADB)
        cls.mod = importlib.import_module('gekko-adb-gtk4')
        cls.app = cls.mod.GekkoAdbGtk4App()
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
        pages = app._stack.get_pages()
        self.assertEqual(len(pages), len(app._catalogo['categorias']))
        self.assertIsNotNone(app._conn_pill_label)
        self.assertIsNotNone(app._term_entry)

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
        self.assertNotIn('()', app._conn_pill_label.get_text())

    def test_confirmar_ejecuta_una_vez(self):
        """Tras aceptar el diálogo de confirmación se lanza el comando (y solo uno)."""
        app = self._activate()
        launched = []
        real_launch = app._launch

        def fake_launch(spec, valores=None, flags=None):
            launched.append(spec['id'])
        app._launch = fake_launch
        try:
            spec = {'id': 'reboot', 'titulo': 'Reiniciar', 'desc': 'adb reboot', 'accion': 'reboot',
                    'args': {'mode': 'normal'}, 'peligro': True, 'confirmar': True}
            confirms = []
            orig_confirm = app._confirm_dialog

            def spy_confirm(spec, valores, flags):
                confirms.append(spec['id'])
                return orig_confirm(spec, valores, flags)
            app._confirm_dialog = spy_confirm
            app._on_command(None, spec)
            _pump(100)
            self.assertEqual(confirms, ['reboot'])
            self.assertEqual(launched, [])
            dialog = None
            for w in Gtk.Window.list_toplevels():
                if isinstance(w, Gtk.Dialog) and w.get_title().startswith('¿Confirmar'):
                    dialog = w
            self.assertIsNotNone(dialog)
            dialog.response(Gtk.ResponseType.OK)
            _pump(200)
            self.assertEqual(launched, ['reboot'])
            self.assertEqual(confirms, ['reboot'])
        finally:
            app._launch = real_launch
            app._confirm_dialog = orig_confirm

    def test_confirmar_cancelar_no_ejecuta(self):
        app = self._activate()
        launched = []
        app._launch = lambda spec, valores=None, flags=None: launched.append(spec['id'])
        try:
            spec = {'id': 'pm_clear', 'titulo': 'Limpiar', 'desc': '', 'accion': 'pm_action',
                    'args': {'action': 'clear'}, 'confirmar': True}
            dialog = app._confirm_dialog(spec, {'package': 'com.a'}, [])
            dialog.response(Gtk.ResponseType.CANCEL)
            _pump(100)
            self.assertEqual(launched, [])
        finally:
            del app._launch

    def test_campos_dialog_valida_y_entrega(self):
        app = self._activate()
        got = []
        app._run_spec = lambda spec, valores=None, flags=None: got.append((valores, flags))
        try:
            spec = app._catalogo and next(c for k in app._catalogo['categorias'] for c in k['comandos'] if c['id'] == 'install_multiple')
            dialog = app._campos_dialog(spec)
            widgets = None
            for w in Gtk.Window.list_toplevels():
                if w is dialog:
                    widgets = w
            self.assertIsNotNone(widgets)
            grid = dialog.get_content_area().get_first_child()
            box = grid.get_child_at(1, 0)
            entry = box.get_first_child()
            entry.set_text('')
            dialog.response(Gtk.ResponseType.OK)
            _pump(100)
            self.assertEqual(got, [], 'con el campo vacío no debe ejecutarse')
            entry.set_text('/tmp/a.apk\n/tmp/b.apk')
            dialog.response(Gtk.ResponseType.OK)
            _pump(100)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0][0]['apks'], '/tmp/a.apk\n/tmp/b.apk')
            self.assertEqual(got[0][1], ['-r', '-g'])
        finally:
            del app._run_spec

    def test_terminal_card_enfoca_consola(self):
        app = self._activate()
        spec = {'id': 'terminal', 'titulo': 'Consola', 'desc': '', 'accion': 'terminal', 'especial': 'terminal'}
        launched = []
        app._run_spec = lambda *a, **k: launched.append(1)
        try:
            app._on_command(None, spec)
            self.assertEqual(launched, [])
        finally:
            del app._run_spec

    def test_consola_autoscroll_mark(self):
        app = self._activate()
        for i in range(60):
            app._log(f'línea {i}')
        buf = app._console_buf
        self.assertEqual(buf.get_iter_at_mark(app._end_mark).get_offset(), buf.get_end_iter().get_offset())


if __name__ == '__main__':
    unittest.main()
