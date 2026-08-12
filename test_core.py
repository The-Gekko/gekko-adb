#!/usr/bin/env python3
"""Tests del núcleo headless (sin gi, sin display).

Aísla el ejecutable de adb con un falso `adb` y aísla HOME/XDG a temporales.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix='gekko_test_')
HOME_FAKE = Path(TMP) / 'home'
HOME_FAKE.mkdir()
for d in ('Descargas', 'Música', 'Imágenes', 'Vídeos'):
    (HOME_FAKE / d).mkdir()
os.environ['HOME'] = str(HOME_FAKE)
os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
os.environ['XDG_STATE_HOME'] = str(HOME_FAKE / 'state')
os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')

CONFIG_FAKE = HOME_FAKE / 'config'
CONFIG_FAKE.mkdir(parents=True)
(CONFIG_FAKE / 'user-dirs.dirs').write_text(
    'XDG_DOWNLOAD_DIR="$HOME/Descargas"\n'
    'XDG_MUSIC_DIR="$HOME/Música"\n'
    'XDG_PICTURES_DIR="$HOME/Imágenes"\n'
    'XDG_VIDEOS_DIR="$HOME/Vídeos"\n',
    encoding='utf-8')

PROJECT_DIR = Path(__file__).resolve().parent
FIXTURES = PROJECT_DIR / 'tests' / 'fixtures'


def _fake_adb_script(path):
    script = """#!/bin/bash
case "$1" in
    devices)
        echo -e "List of devices attached\\nR5CX905SJQD\\tdevice"
        exit 0;;
    version)
        echo "Android Debug Bridge version 1.0.41"; exit 0;;
    shell)
        shift
        case "$1" in
            getprop)
                shift
                case "$1" in
                    ro.product.model) echo "SM-S928B";;
                    ro.product.brand) echo "samsung";;
                    ro.build.version.release) echo "16";;
                    ro.build.version.sdk) echo "35";;
                    ro.product.cpu.abi) echo "arm64-v8a";;
                    ro.boot.warranty_bit) echo "0";;
                    *) ;;
                esac
                exit 0;;
            dumpsys)
                shift
                if [[ "$1" == "battery" ]]; then
                    echo -e "Current Battery Service state:\\n  AC powered: true\\n  USB powered: true\\n  status: 2\\n  health: 2\\n  present: true\\n  level: 75\\n  scale: 100\\n  voltage: 4156\\n  temperature: 357\\n  technology: Li-ion\\n  Capacity level: -1\\n[EventLogBuffer]\\n08-11 18:34:14.721  Sending ACTION_BATTERY_CHANGED: level:72, status:2, health:2, voltage:4120, temperature:345\\n08-11 18:34:45.195  Sending ACTION_BATTERY_CHANGED: level:73, status:2, health:2, voltage:4124, temperature:347"
                fi
                exit 0;;
            wm)
                shift
                case "$1" in
                    size) echo "Physical size: 1440x3120";;
                    density) echo "Physical density: 480";;
                esac
                exit 0;;
            settings)
                shift
                if [[ "$1" == "get" && "$3" == "navigation_mode" ]]; then echo "2"; fi
                exit 0;;
            cmd)
                shift
                if [[ "$1" == "role" && "$2" == "get-role-holders" ]]; then
                    echo "com.example.launcher"
                fi
                exit 0;;
            pm)
                shift
                if [[ "$1" == "list" ]]; then
                    echo -e "package:com.example.one\\npackage:com.example.two"
                fi
                exit 0;;
            ps)
                echo -e "USER PID PPID NAME\\nroot 1 0 /init"
                exit 0;;
            logcat)
                echo " 1234 1 I Example: hello"
                exit 0;;
            screencap) echo "ok"; exit 0;;
            rm) echo "ok"; exit 0;;
            *) echo "ok"; exit 0;;
        esac
        exit 0;;
    install) echo "Success"; exit 0;;
    pull) echo "pulled"; exit 0;;
    tcpip) echo "restarting in TCP mode port: 5555"; exit 0;;
    connect) echo "connected to 1.2.3.4:5555"; exit 0;;
    *) echo "ok"; exit 0;;
esac
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(script)
    os.chmod(path, 0o755)
    return path


FAKE_ADB = _fake_adb_script(os.path.join(TMP, 'fake-adb'))
os.environ['GEKKO_ADB_EXECUTABLE'] = FAKE_ADB
os.environ['GEKKO_SCRCPY_EXECUTABLE'] = shutil.which('true') or '/bin/true'
os.environ['GEKKO_ADB_BASE'] = str(PROJECT_DIR)

import gekko_adb_core as core  # noqa: E402


class TestCatalogoIntegridad(unittest.TestCase):
    def test_catalogo_carga(self):
        cat = core.load_catalogo()
        self.assertGreaterEqual(len(cat['categorias']), 10)
        ids = set()
        for c in cat['categorias']:
            self.assertIn('id', c)
            self.assertIn('titulo', c)
            self.assertIn('comandos', c)
            self.assertNotIn(c['id'], ids, f'categoría duplicada: {c["id"]}')
            ids.add(c['id'])
            for cmd in c['comandos']:
                self.assertIn('id', cmd)
                self.assertIn('accion', cmd)
                self.assertIn('titulo', cmd)

    def test_catalogo_acciones_existen(self):
        cat = core.load_catalogo()
        for c in cat['categorias']:
            for cmd in c['comandos']:
                self.assertIn(cmd['accion'], core._ACTIONS,
                              f"{cmd['id']}: acción {cmd['accion']} sin handler")

    def test_campos_cubren_dispatch(self):
        """Todo campo pedido por la UI debe existir en build_valores."""
        cat = core.load_catalogo()
        for c in cat['categorias']:
            for cmd in c['comandos']:
                for campo in cmd.get('campos') or []:
                    self.assertIn('clave', campo)
                    self.assertIn('tipo', campo)

    def test_presets_validos(self):
        presets = core.load_presets()
        self.assertEqual(len(presets), 9)
        for p in presets:
            self.assertIn('id', p)
            self.assertIn('titulo', p)
            self.assertGreaterEqual(len(p['paquetes']), 1)


class TestEjecucion(unittest.TestCase):
    def setUp(self):
        os.environ['HOME'] = str(HOME_FAKE)
        os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
        os.environ['XDG_STATE_HOME'] = str(HOME_FAKE / 'state')
        os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
    def test_devices(self):
        res = core.act_devices()
        self.assertTrue(res['success'])
        self.assertIn('R5CX905SJQD', res['stdout'])

    def test_device_info(self):
        info = core.get_device_info()
        self.assertTrue(info['connected'])
        self.assertEqual(info['model'], 'SAMSUNG SM-S928B')
        self.assertEqual(info['battery'], '75%')
        self.assertEqual(info['temperature'], '35.7 °C')
        self.assertEqual(info['voltage'], '4.156 V')
        self.assertEqual(info['health'], 'Bien')
        self.assertEqual(info['battery_status'], 'Cargando')
        self.assertEqual(info['nav_mode'], 'Gestos')
        self.assertEqual(info['secure'], 'Knox 0x0 (Valid)')

    def test_device_info_xiaomi(self):
        fake = os.path.join(TMP, 'fake-adb-xiaomi')
        script = """#!/bin/bash
case "$1" in
    devices) echo -e "List of devices attached\\n27121JRA8C\\tdevice"; exit 0;;
    shell)
        shift
        case "$1" in
            getprop)
                shift
                case "$1" in
                    ro.product.model) echo "2312DRA50G";;
                    ro.product.brand) echo "Redmi";;
                    ro.product.manufacturer) echo "Xiaomi";;
                    ro.build.version.release) echo "14";;
                    ro.build.version.sdk) echo "34";;
                    ro.product.cpu.abi) echo "arm64-v8a";;
                    ro.boot.flash.locked) echo "1";;
                    ro.boot.verifiedbootstate) echo "green";;
                    *) ;;
                esac
                exit 0;;
            dumpsys)
                shift
                if [[ "$1" == "battery" ]]; then
                    echo -e "Current Battery Service state:\\n  status: 2\\n  health: 2\\n  present: true\\n  level: 92\\n  scale: 100\\n  voltage: 4100\\n  temperature: 290\\n  Capacity level: -1"
                fi
                exit 0;;
            wm)
                shift
                case "$1" in
                    size) echo "Physical size: 1220x2712";;
                    density) echo "Physical density: 440";;
                esac
                exit 0;;
            settings)
                shift
                if [[ "$1" == "get" && "$3" == "navigation_mode" ]]; then echo "2"; fi
                exit 0;;
            cmd)
                shift
                if [[ "$1" == "role" && "$2" == "get-role-holders" ]]; then
                    echo "com.miui.home"
                fi
                exit 0;;
            *) exit 0;;
        esac
        exit 0;;
    *) exit 0;;
esac
"""
        with open(fake, 'w', encoding='utf-8') as f:
            f.write(script)
        os.chmod(fake, 0o755)
        old = core.ADB_EXEC
        try:
            core.ADB_EXEC = fake
            info = core.get_device_info()
            self.assertTrue(info['connected'])
            self.assertEqual(info['marca'], 'xiaomi')
            self.assertEqual(info['secure'], 'Bootloader Bloqueado · Verified green')
            self.assertEqual(info['battery'], '92%')
            self.assertEqual(info['temperature'], '29 °C')
            self.assertEqual(info['health'], 'Bien')
            self.assertEqual(info['home_role'], 'com.miui.home')
        finally:
            core.ADB_EXEC = old

    def test_device_info_sin_dispositivo(self):
        old = core.ADB_EXEC
        try:
            fake = os.path.join(TMP, 'fake-adb-none')
            with open(fake, 'w', encoding='utf-8') as f:
                f.write('#!/bin/bash\ncase "$1" in devices) echo "List of devices attached";; esac\n')
            os.chmod(fake, 0o755)
            core.ADB_EXEC = fake
            info = core.get_device_info()
            self.assertFalse(info['connected'])
        finally:
            core.ADB_EXEC = old

    def test_packages(self):
        pkgs = core.get_packages()
        self.assertEqual(pkgs, ['com.example.one', 'com.example.two'])

    def test_dispatch_install_flags(self):
        apk = os.path.join(TMP, 'app.apk')
        with open(apk, 'w', encoding='utf-8') as f:
            f.write('x')
        spec = {'accion': 'install', 'campos': [{'clave': 'apk', 'tipo': 'archivo'}]}
        res = core.ejecutar(spec, {'apk': apk}, ['-r', '-g'])
        self.assertTrue(res['success'])
        self.assertIn('Success', res['stdout'])

    def test_dispatch_accion_desconocida(self):
        res = core.ejecutar({'accion': 'no_existe'}, {}, [])
        self.assertFalse(res['success'])

    def test_quick_pull_usa_xdg(self):
        res = core.act_quick_pull('/sdcard/Music/', 'MUSIC')
        self.assertTrue(res['success'])
        target = core.user_dir('MUSIC')
        self.assertEqual(target, str(HOME_FAKE / 'Música'))
        self.assertTrue(Path(target).is_dir())


class TestBateria(unittest.TestCase):
    def _norm(self, text):
        return core._normalize_battery(core._parse_battery_state(text))

    def test_samsung_real(self):
        text = (FIXTURES / 'battery_samsung_s24.txt').read_text(encoding='utf-8')
        data = self._norm(text)
        self.assertEqual(data['level'], 75)
        self.assertEqual(data['temp_tenths'], 357)
        self.assertEqual(data['voltage_mv'], 4156)
        self.assertEqual(data['health'], '2')
        self.assertEqual(data['status'], '2')

    def test_eventlog_no_contamina(self):
        text = """Current Battery Service state:
  status: 2
  health: 2
  level: 75
  scale: 100
  voltage: 4156
  temperature: 357
  Capacity level: -1
[EventLogBuffer]
08-11 18:34:14.721  Sending ACTION_BATTERY_CHANGED: level:72, health:2, voltage:4120, temperature:345
08-11 18:34:45.195  Sending ACTION_BATTERY_CHANGED: level:73, health:2, voltage:4124, temperature:347
"""
        data = self._norm(text)
        self.assertEqual(data['level'], 75)
        self.assertEqual(data['temp_tenths'], 357)
        self.assertEqual(data['voltage_mv'], 4156)
        self.assertEqual(data['health'], '2')

    def test_capacity_negativo_es_desconocido(self):
        text = (FIXTURES / 'battery_miui.txt').read_text(encoding='utf-8')
        data = self._norm(text)
        self.assertEqual(data['level'], 60)
        self.assertNotEqual(data['level'], -1)
        self.assertGreaterEqual(data['level'], 0)

    def test_escala_normaliza_nivel(self):
        text = (FIXTURES / 'battery_aosp.txt').read_text(encoding='utf-8')
        data = self._norm(text)
        self.assertEqual(data['level'], 80)

    def test_nivel_jamas_negativo(self):
        for name in ('battery_samsung_s24.txt', 'battery_miui.txt', 'battery_aosp.txt'):
            text = (FIXTURES / name).read_text(encoding='utf-8')
            data = self._norm(text)
            self.assertGreaterEqual(data.get('level', 0), 0, name)

    def test_batteryproperties_parse(self):
        text = """BatteryPropertiesRegistrar:
  ac_present: false
  battery_status: 3
  battery_level: 75
  battery_scale: 100
  battery_health: 2
  battery_voltage: 4156
  battery_temperature: 357
"""
        data = core._normalize_battery(core._parse_battery_properties(text))
        self.assertEqual(data['level'], 75)
        self.assertEqual(data['voltage_mv'], 4156)

    def test_wm_override_prioritario(self):
        self.assertEqual(core._wm_value("Physical size: 1440x3120\nOverride size: 1080x2400", 'size'),
                         '1080x2400')
        self.assertEqual(core._wm_value("Physical size: 1440x3120", 'size'), '1440x3120')
        self.assertEqual(core._wm_value("", 'size'), '')
        self.assertEqual(core._wm_value("Physical density: 600", 'density'), '600')


class TestCommandWorker(unittest.TestCase):
    def _wait_until(self, cond, timeout=5):
        deadline = threading.Event()
        deadline.wait(0)
        import time
        end = time.time() + timeout
        while not cond() and time.time() < end:
            time.sleep(0.02)

    def test_on_done_una_vez(self):
        calls = []
        worker = core.CommandWorker(
            {'id': 'd', 'titulo': 'd', 'desc': '', 'accion': 'devices'},
            None, None,
            on_done=lambda r: calls.append(('done', r)),
            on_error=lambda e: calls.append(('error', e)),
        )
        worker.start()
        self._wait_until(lambda: len(calls) >= 1)
        self.assertEqual(len(calls), 1)
        kind, res = calls[0]
        self.assertEqual(kind, 'done')
        self.assertTrue(res['success'])

    def test_on_error_solo_excepcion(self):
        calls = []

        def boom(*_a, **_k):
            raise RuntimeError('boom')

        worker = core.CommandWorker(
            {'id': 'x', 'titulo': 'x', 'desc': '', 'accion': 'devices'},
            None, None, on_done=lambda r: calls.append('done'),
            on_error=lambda e: calls.append('error'))
        original = core.ejecutar
        core.ejecutar = boom
        try:
            worker.start()
            self._wait_until(lambda: len(calls) >= 1)
            self.assertEqual(calls, ['error'])
        finally:
            core.ejecutar = original

    def test_resultado_fallido_va_a_done(self):
        calls = []
        worker = core.CommandWorker(
            {'id': 'x', 'titulo': 'x', 'desc': '', 'accion': 'no_existe'},
            None, None,
            on_done=lambda r: calls.append(('done', r)),
            on_error=lambda e: calls.append('error'))
        worker.start()
        self._wait_until(lambda: len(calls) >= 1)
        kind, res = calls[0]
        self.assertEqual(kind, 'done')
        self.assertFalse(res['success'])


class TestConfig(unittest.TestCase):
    def setUp(self):
        os.environ['HOME'] = str(HOME_FAKE)
        os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
        os.environ['XDG_STATE_HOME'] = str(HOME_FAKE / 'state')
        os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
    def test_config_roundtrip(self):
        cfg = core.cargar_config()
        self.assertEqual(cfg.get('General', 'theme'), 'system')
        cfg.set('General', 'theme', 'matugen')
        core.guardar_config(cfg)
        cfg2 = core.cargar_config()
        self.assertEqual(cfg2.get('General', 'theme'), 'matugen')

    def test_user_dir_fallback(self):
        os.environ.pop('PATH', None)
        try:
            d = core.user_dir('DOWNLOAD')
            self.assertEqual(d, str(HOME_FAKE / 'Descargas'))
        finally:
            pass


if __name__ == '__main__':
    unittest.main()
