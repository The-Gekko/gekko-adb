#!/usr/bin/env python3
"""Tests del núcleo headless (sin gi, sin display).

Un `adb` falso registra el argv EXACTO de cada llamada en un archivo, así
cada test afirma el comando real que se envía a adb, no solo 'success'.
El escenario del adb falso (1 dispositivo, 2, sin autorizar, sin
dispositivo, errores) se elige escribiendo un archivo de escenario.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix='gekko_test_')
HOME_FAKE = Path(TMP) / 'home'
HOME_FAKE.mkdir()
for d in ('Descargas', 'Música', 'Imágenes', 'Vídeos'):
    (HOME_FAKE / d).mkdir()
os.environ['HOME'] = str(HOME_FAKE)
os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
os.environ['XDG_STATE_HOME'] = str(HOME_FAKE / 'state')
os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
(HOME_FAKE / 'config').mkdir(parents=True)

PROJECT_DIR = Path(__file__).resolve().parent
FIXTURES = PROJECT_DIR / 'tests' / 'fixtures'
# Otros módulos de test reescriben HOME/XDG_* al importarse (discover los
# importa todos antes de ejecutar): cada test restablece su propio entorno.
ENV = {k: os.environ[k] for k in ('HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME')}
ARGV_LOG = Path(TMP) / 'argv.log'
SCENARIO = Path(TMP) / 'scenario'
SCENARIO.write_text('default')

FAKE_ADB_SCRIPT = r'''#!/bin/bash
# adb falso: registra el argv y responde según el escenario.
printf '%s\n' "$(printf '%s\x1f' "$@")" >> "$GEKKO_TEST_ARGV_LOG"
scen="$(cat "$GEKKO_TEST_SCENARIO" 2>/dev/null || echo default)"
args=("$@")
if [[ "${args[0]}" == "-s" ]]; then args=("${args[@]:2}"); fi
case "${args[0]}" in
    devices)
        echo "List of devices attached"
        case "$scen" in
            none) ;;
            two) echo "SERIAL1               device usb:1-1 product:e3q model:SM_S928B"; echo "SERIAL2               device usb:1-2 product:x model:Y";;
            unauth) echo "SERIAL1               device usb:1-1 product:e3q model:SM_S928B"; echo "192.168.1.9:5555       unauthorized";;
            noperm) echo "SERIAL1               no permissions (user in plugdev group; are your udev rules wrong?); see [http://developer.android.com/tools/device.html]";;
            *) echo "SERIAL1               device usb:1-1 product:e3q model:SM_S928B transport_id:1";;
        esac
        exit 0;;
    version) echo "Android Debug Bridge version 1.0.41"; echo "Version 37.0.0"; exit 0;;
    connect)
        if [[ "$scen" == "connect_fail" ]]; then echo "failed to connect to '${args[1]}': Connection refused"; exit 0; fi
        echo "connected to ${args[1]}"; exit 0;;
    root)
        if [[ "$scen" == "root_prod" ]]; then echo "adbd cannot run as root in production builds"; exit 0; fi
        echo "restarting adbd as root"; exit 0;;
    unroot) echo "restarting adbd as non root"; exit 0;;
    tcpip) echo "restarting in TCP mode port: ${args[1]}"; exit 0;;
    pair) echo "Successfully paired to ${args[1]} [guid=adb-x]"; exit 0;;
    install|install-multiple|install-multi-package) echo "Performing Streamed Install"; echo "Success"; exit 0;;
    uninstall) echo "Success"; exit 0;;
    pull)
        echo "1 file pulled, 0 skipped."
        last="${args[-1]}"
        if [[ "$scen" == "pull_dir" ]]; then mkdir -p "$last/sub"; echo x > "$last/a.txt"; echo y > "$last/sub/b.txt"; fi
        exit 0;;
    exec-out)
        if [[ "$scen" == "shot_fail" ]]; then echo "error: no devices" >&2; exit 1; fi
        printf '\x89PNG\r\n\x1a\nfake'; exit 0;;
    logcat) exit 0;;
    shell)
        if [[ "$scen" == "shell_fail" ]]; then echo "error: device offline" >&2; exit 1; fi
        case "${args[1]}" in
            getprop)
                case "${args[2]}" in
                    ro.product.model) echo "SM-S928B";;
                    ro.product.brand) echo "samsung";;
                    ro.product.manufacturer) echo "samsung";;
                    ro.build.version.release) echo "16";;
                    ro.build.version.sdk) if [[ "$scen" == "android13" ]]; then echo "33"; else echo "36"; fi;;
                    ro.product.cpu.abi) echo "arm64-v8a";;
                    ro.boot.warranty_bit) if [[ "$scen" != "noknox" ]]; then echo "0"; fi;;
                    *) ;;
                esac
                exit 0;;
            setprop)
                if [[ "$scen" == "setprop_fail" || "${args[2]}" == persist.* || "${args[2]}" == ctl.* ]]; then
                    echo "setprop: failed to set property '${args[2]}' to '${args[3]}'" >&2; exit 1
                fi
                exit 0;;
            dumpsys)
                if [[ "${args[2]}" == "battery" && "${#args[@]}" -eq 3 ]]; then
                    cat "$GEKKO_TEST_FIXTURES/battery_samsung_s24.txt"
                fi
                exit 0;;
            wm)
                case "${args[2]}" in
                    size) echo "Physical size: 1440x3120";;
                    density) echo "Physical density: 480";;
                esac
                exit 0;;
            settings)
                if [[ "${args[2]}" == "get" && "${args[4]}" == "navigation_mode" ]]; then echo "2"; fi
                if [[ "${args[2]}" == "get" && "${args[4]}" == "sms_default_application" ]]; then echo "com.samsung.android.messaging"; fi
                if [[ "${args[2]}" == "put" && "$scen" == "settings_fail" ]]; then echo "error"; exit 1; fi
                exit 0;;
            cmd)
                if [[ "${args[2]}" == "role" && "${args[3]}" == "get-role-holders" ]]; then
                    if [[ "$scen" == "android13" ]]; then echo "Unknown command: get-role-holders"; exit 255; fi
                    echo "com.example.launcher"
                fi
                if [[ "${args[2]}" == "package" && "${args[3]}" == "resolve-activity" ]]; then
                    echo "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true"; echo "com.miui.home/.launcher.Launcher"
                fi
                if [[ "${args[2]}" == "package" && "${args[3]}" == "uninstall" ]]; then echo "Success"; fi
                if [[ "${args[2]}" == "package" && "${args[3]}" == "install-existing" ]]; then echo "Package ${args[4]} installed for user: 0"; fi
                if [[ "${args[2]}" == "overlay" ]]; then echo ""; fi
                exit 0;;
            pm)
                if [[ "${args[2]}" == "list" ]]; then
                    if [[ "$scen" == "pm_fail" ]]; then echo "error: closed" >&2; exit 1; fi
                    echo "package:com.example.two"; echo "package:com.example.one"
                fi
                if [[ "${args[2]}" == "path" ]]; then
                    if [[ "$scen" == "splits" ]]; then echo "package:/data/app/x/base.apk"; echo "package:/data/app/x/split_config.arm64_v8a.apk"; else echo "package:/data/app/x/base.apk"; fi
                fi
                if [[ "${args[2]}" == "uninstall" ]]; then
                    if [[ "${args[5]}" == "com.absent" ]]; then echo "Failure [not installed for 0]"; exit 1; fi
                    if [[ "${args[5]}" == "com.protected" ]]; then echo "Failure [DELETE_FAILED_DEVICE_POLICY_MANAGER]"; exit 1; fi
                    echo "Success"
                fi
                exit 0;;
            monkey) echo "Events injected: 1"; exit 0;;
            ps) echo "USER PID PPID NAME"; echo "root 1 0 /init"; exit 0;;
            logcat) echo " 1234 1 I Example: hello"; echo " 1234 1 E Crash: boom"; exit 0;;
            top) printf 'Tasks: 3 total\r\n  PID USER\r\n'; exit 0;;
            ip) echo "    inet 192.168.1.42/24 brd 192.168.1.255 scope global wlan0"; exit 0;;
            *) exit 0;;
        esac;;
    *) exit 0;;
esac
'''


def _write_fake(path):
    Path(path).write_text(FAKE_ADB_SCRIPT, encoding='utf-8')
    os.chmod(path, 0o755)
    return path


FAKE_ADB = _write_fake(os.path.join(TMP, 'fake-adb'))
os.environ['GEKKO_ADB_EXECUTABLE'] = FAKE_ADB
os.environ['GEKKO_TEST_ARGV_LOG'] = str(ARGV_LOG)
os.environ['GEKKO_TEST_SCENARIO'] = str(SCENARIO)
os.environ['GEKKO_TEST_FIXTURES'] = str(FIXTURES)
os.environ['GEKKO_SCRCPY_EXECUTABLE'] = shutil.which('true') or '/bin/true'
os.environ['GEKKO_ADB_BASE'] = str(PROJECT_DIR)

import gekko_adb_core as core  # noqa: E402

CAT = core.load_catalogo()
SPECS = {c['id']: c for k in CAT['categorias'] for c in k['comandos']}


def scenario(name):
    SCENARIO.write_text(name)
    core.invalidate_transports()


def calls():
    """Lista de argv (listas) registrados por el adb falso desde el último reset."""
    if not ARGV_LOG.exists():
        return []
    out = []
    for line in ARGV_LOG.read_text(encoding='utf-8').splitlines():
        out.append([a for a in line.split('\x1f') if a != ''][:])
    return out


def reset_calls():
    if ARGV_LOG.exists():
        ARGV_LOG.unlink()
    core.invalidate_transports()


def non_devices(cs):
    return [c for c in cs if c[:1] != ['devices'] and c[:3] != ['devices', '-l']]


class Base(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)
        scenario('default')
        reset_calls()

    def run_spec(self, spec_id, valores=None, flags=None):
        res = core.ejecutar(SPECS[spec_id], valores or {}, flags or [])
        return res, non_devices(calls())


class TestCatalogoIntegridad(Base):
    def test_catalogo_carga(self):
        self.assertGreaterEqual(len(CAT['categorias']), 12)
        ids = [c['id'] for k in CAT['categorias'] for c in k['comandos']]
        self.assertEqual(len(ids), len(set(ids)), 'ids de comando duplicados')
        for c in CAT['categorias']:
            for cmd in c['comandos']:
                self.assertIn(cmd['accion'], core._ACTIONS, f"{cmd['id']}: acción {cmd['accion']} sin handler")
                for campo in cmd.get('campos') or []:
                    self.assertIn('clave', campo)
                    self.assertIn('tipo', campo)
                    self.assertIn(campo['tipo'], ('texto', 'numero', 'select', 'archivo', 'archivos', 'carpeta', 'paquete'))

    def test_presets_validos(self):
        presets = core.load_presets()
        self.assertGreaterEqual(len(presets), 8)
        seen = {}
        for p in presets:
            for pkg in p['paquetes']:
                self.assertRegex(pkg, core._PKG_RE)
                self.assertNotIn(pkg, seen, f'{pkg} duplicado en {seen.get(pkg)} y {p["id"]}')
                seen[pkg] = p['id']
        self.assertNotIn('com.samsung.android.honeyboard', seen)

    def test_preset_buttons_incluye_restaurar(self):
        specs = core.preset_buttons()
        acciones = {s['accion'] for s in specs}
        self.assertEqual(acciones, {'debloat_preset', 'restore_preset'})
        for s in specs:
            if s['accion'] == 'debloat_preset':
                self.assertTrue(s['confirmar'])


class TestArgv(Base):
    """Cada botón produce exactamente el argv esperado."""

    def test_install_flags_llegan(self):
        apk = os.path.join(TMP, 'app.apk')
        Path(apk).write_text('x')
        res, cs = self.run_spec('install', {'apk': apk}, ['-r', '-g', '-d'])
        self.assertTrue(res['success'])
        self.assertEqual(cs, [['install', '-r', '-g', '-d', apk]])

    def test_install_falta_archivo(self):
        res, cs = self.run_spec('install', {'apk': os.path.join(TMP, 'nope.apk')}, ['-r'])
        self.assertFalse(res['success'])
        self.assertIn('No existe', res['stderr'])
        self.assertEqual(cs, [])

    def test_install_multiple_lista_y_string(self):
        a, b = os.path.join(TMP, 'a.apk'), os.path.join(TMP, 'b.apk')
        Path(a).write_text('x'); Path(b).write_text('y')
        res, cs = self.run_spec('install_multiple', {'apks': f'{a}\n{b}'}, ['-r', '-g'])
        self.assertTrue(res['success'])
        self.assertEqual(cs, [['install-multiple', '-r', '-g', a, b]])
        reset_calls()
        res = core.act_install_multiple([a], ['-r'])
        self.assertEqual(non_devices(calls()), [['install-multiple', '-r', a]])

    def test_uninstall_y_k(self):
        res, cs = self.run_spec('uninstall', {'package': 'com.x.y'}, [])
        self.assertEqual(cs, [['uninstall', 'com.x.y']])
        reset_calls()
        res, cs = self.run_spec('uninstall', {'package': 'com.x.y'}, ['-k'])
        self.assertEqual(cs, [['shell', 'cmd', 'package', 'uninstall', '-k', 'com.x.y']])

    def test_paquete_invalido(self):
        res, cs = self.run_spec('uninstall', {'package': '(sin paquetes)'}, [])
        self.assertFalse(res['success'])
        self.assertIn('no válido', res['stderr'])
        self.assertEqual(cs, [])

    def test_soft_reboot_usa_setprop(self):
        res, cs = self.run_spec('soft_reboot')
        self.assertEqual(cs, [['shell', 'setprop', 'ctl.restart', 'zygote']])
        self.assertFalse(res['success'])
        self.assertIn('root', res['stderr'])

    def test_safemode_no_reinicia_si_setprop_falla(self):
        res, cs = self.run_spec('safemode')
        self.assertEqual(cs, [['shell', 'setprop', 'persist.sys.safemode', '1']])
        self.assertFalse(res['success'])

    def test_reboot_modes(self):
        for sid, expected in (('reboot', ['reboot']), ('rb_recovery', ['reboot', 'recovery']),
                              ('rb_download', ['reboot', 'download']), ('rb_fastboot', ['reboot', 'fastboot'])):
            reset_calls()
            res, cs = self.run_spec(sid)
            self.assertEqual(cs, [expected], sid)

    def test_input_text_escapa(self):
        res, cs = self.run_spec('text', {'text': 'hola mundo & ls'})
        self.assertEqual(cs, [['shell', 'input', 'text', "'hola%smundo%s&%sls'"]])

    def test_input_validacion_numeros(self):
        res, cs = self.run_spec('tap', {'x': 'abc', 'y': '10'})
        self.assertFalse(res['success'])
        self.assertIn('número', res['stderr'])
        self.assertEqual(cs, [])
        res, cs = self.run_spec('swipe', {'x1': '1', 'y1': '2', 'x2': '3', 'y2': '4', 'dur': '300'})
        self.assertEqual(cs, [['shell', 'input', 'swipe', '1', '2', '3', '4', '300']])

    def test_keyevents(self):
        for sid, code in (('key_home', '3'), ('key_recents', '187'), ('key_mute', '164'), ('key_wake', '224')):
            reset_calls()
            res, cs = self.run_spec(sid)
            self.assertEqual(cs, [['shell', 'input', 'keyevent', code]], sid)

    def test_custom_shlex_y_prefijo_adb(self):
        res, cs = self.run_spec('custom', {'command': 'shell input text "hola mundo"'})
        self.assertEqual(cs, [['shell', 'input', 'text', 'hola mundo']])
        reset_calls()
        res, cs = self.run_spec('custom', {'command': 'adb shell ls'})
        self.assertEqual(cs, [['shell', 'ls']])
        reset_calls()
        res, cs = self.run_spec('custom', {'command': 'logcat *:E'})
        self.assertEqual(cs, [['logcat', '-d', '*:E']])
        reset_calls()
        res, cs = self.run_spec('custom', {'command': 'shell "sin cerrar'})
        self.assertFalse(res['success'])
        self.assertEqual(cs, [])
        res, cs = self.run_spec('custom', {'command': '   '})
        self.assertFalse(res['success'])

    def test_top_batch(self):
        res, cs = self.run_spec('db_cpu')
        self.assertEqual(cs, [['shell', 'top', '-b', '-n', '1', '-m', '40']])
        self.assertNotIn('\r', res['stdout'])

    def test_logcat_read(self):
        res, cs = self.run_spec('logcat_read', {'level': 'E', 'filter': 'crash'})
        self.assertEqual(cs, [['shell', 'logcat', '-d', '-t', '2000', "'*:E'"]])
        self.assertTrue(res['success'])
        self.assertIn('Crash: boom', res['stdout'])
        self.assertNotIn('hello', res['stdout'])

    def test_pm_actions(self):
        res, cs = self.run_spec('pm_disable', {'package': 'com.a.b'})
        self.assertEqual(cs, [['shell', 'pm', 'disable-user', '--user', '0', 'com.a.b']])
        reset_calls()
        res, cs = self.run_spec('pm_grant', {'package': 'com.a.b', 'permission': 'android.permission.READ_LOGS'})
        self.assertEqual(cs, [['shell', 'pm', 'grant', 'com.a.b', 'android.permission.READ_LOGS']])

    def test_settings_put_quote(self):
        res, cs = self.run_spec('settings_put', {'space': 'global', 'key': 'k', 'value': 'a b'})
        self.assertEqual(cs, [['shell', 'settings', 'put', 'global', 'k', "'a b'"]])
        res, cs = self.run_spec('settings_put', {'space': 'otro', 'key': 'k', 'value': '1'})
        self.assertFalse(res['success'])

    def test_nav_mode_usa_overlay(self):
        res, cs = self.run_spec('nav_gestos')
        self.assertIn(['shell', 'cmd', 'overlay', 'enable-exclusive', '--category',
                       'com.android.internal.systemui.navbar.gestural'], cs)
        self.assertIn(['shell', 'settings', 'put', 'global', 'navigation_bar_gesture_while_hidden', '1'], cs)
        self.assertTrue(res['success'])

    def test_anim_scale_propaga_error(self):
        res, cs = self.run_spec('anim_off')
        self.assertTrue(res['success'])
        self.assertEqual(len(cs), 3)
        scenario('settings_fail')
        res, cs = self.run_spec('anim_off')
        self.assertFalse(res['success'])

    def test_wm(self):
        res, cs = self.run_spec('density', {'dpi': '420'})
        self.assertEqual(cs, [['shell', 'wm', 'density', '420']])
        res, cs = self.run_spec('wm_size', {'size': '1080x2400'})
        self.assertEqual(cs[-1], ['shell', 'wm', 'size', '1080x2400'])
        res, cs = self.run_spec('wm_size', {'size': '1080 2400'})
        self.assertFalse(res['success'])

    def test_role_set(self):
        res, cs = self.run_spec('rol_dialer_xiaomi')
        self.assertEqual(cs, [['shell', 'cmd', 'role', 'add-role-holder', 'android.app.role.DIALER', 'com.android.contacts']])
        reset_calls()
        res, cs = self.run_spec('role_custom', {'role': 'android.app.role.HOME', 'package': 'x'})
        self.assertFalse(res['success'])
        self.assertEqual(cs, [])

    def test_forward_reverse_orden(self):
        res, cs = self.run_spec('f_add', {'local': 'tcp:1', 'remoto': 'tcp:2'})
        self.assertEqual(cs, [['forward', 'tcp:1', 'tcp:2']])
        reset_calls()
        res, cs = self.run_spec('r_add', {'remoto': 'tcp:3', 'local': 'tcp:4'})
        self.assertEqual(cs, [['reverse', 'tcp:3', 'tcp:4']])

    def test_screenshot_exec_out(self):
        res, cs = self.run_spec('screenshot')
        self.assertTrue(res['success'])
        self.assertEqual(cs, [['exec-out', 'screencap', '-p']])
        self.assertTrue(os.path.exists(res['path']))
        self.assertTrue(res['path'].startswith(str(HOME_FAKE / 'Imágenes')))
        scenario('shot_fail')
        reset_calls()
        res, cs = self.run_spec('screenshot')
        self.assertEqual(cs[0], ['exec-out', 'screencap', '-p'])
        self.assertEqual(cs[1], ['shell', 'screencap', '-p', '/sdcard/gekko_screen.png'])

    def test_screenrecord(self):
        res, cs = self.run_spec('screenrecord', {'seconds': '5'})
        self.assertEqual(cs[0], ['shell', 'screenrecord', '--time-limit', '5', '/sdcard/gekko_screenrecord.mp4'])
        self.assertEqual(cs[1][:2], ['pull', '/sdcard/gekko_screenrecord.mp4'])
        res, cs = self.run_spec('screenrecord', {'seconds': '999'})
        self.assertFalse(res['success'])

    def test_extract_apk_splits(self):
        res, cs = self.run_spec('extract', {'package': 'com.x'})
        self.assertTrue(res['success'])
        self.assertTrue(res['path'].endswith('com.x.apk'))
        scenario('splits')
        reset_calls()
        res, cs = self.run_spec('extract', {'package': 'com.x'})
        self.assertTrue(res['success'])
        self.assertTrue(res['path'].endswith('/com.x'))
        self.assertEqual(len([c for c in cs if c[0] == 'pull']), 2)
        self.assertIn('splits', res['stdout'])

    def test_pull_vacio_y_push(self):
        res, cs = self.run_spec('pull', {'origen': '/sdcard/x', 'destino': ''})
        self.assertFalse(res['success'])
        self.assertIn('Carpeta destino', res['stderr'])
        self.assertEqual(cs, [])
        res, cs = self.run_spec('push', {'origen': '', 'destino': '/sdcard/'})
        self.assertFalse(res['success'])
        self.assertEqual(cs, [])
        src = os.path.join(TMP, 'f.txt'); Path(src).write_text('x')
        res, cs = self.run_spec('push', {'origen': src, 'destino': '/sdcard/Download/'})
        self.assertEqual(cs, [['push', src, '/sdcard/Download/']])
        reset_calls()
        res, cs = self.run_spec('sync_push', {'origen': TMP, 'destino': '/sdcard/x'})
        self.assertEqual(cs, [['push', '--sync', TMP, '/sdcard/x']])

    def test_quick_pull_fusiona_sin_anidar(self):
        scenario('pull_dir')
        res, cs = self.run_spec('q_camara')
        self.assertTrue(res['success'])
        target = HOME_FAKE / 'Imágenes' / 'Camera'
        self.assertEqual(cs[0][:2], ['pull', '/sdcard/DCIM/Camera'])
        self.assertTrue((target / 'a.txt').is_file())
        self.assertTrue((target / 'sub' / 'b.txt').is_file())
        self.assertFalse(any(p.name.startswith('.gekko_pull') for p in target.iterdir()))

    def test_host_commands_sin_serial(self):
        scenario('two')
        for sid, expected in (('devices', ['devices', '-l']), ('host_features', ['host-features']),
                              ('f_list', ['forward', '--list']), ('mdns_check', ['mdns', 'check'])):
            reset_calls()
            res = core.ejecutar(SPECS[sid], {}, [])
            self.assertEqual(calls()[-1], expected, sid)

    def test_device_commands_con_dos_dispositivos(self):
        scenario('two')
        for sid, valores, expected in (
                ('tcpip', {'port': '5555'}, ['-s', 'SERIAL1', 'tcpip', '5555']),
                ('usb', {}, ['-s', 'SERIAL1', 'usb']),
                ('root', {}, ['-s', 'SERIAL1', 'root']),
                ('remount', {}, ['-s', 'SERIAL1', 'remount']),
                ('f_clear', {}, ['-s', 'SERIAL1', 'forward', '--remove-all']),
                ('r_list', {}, ['-s', 'SERIAL1', 'reverse', '--list']),
                ('key_home', {}, ['-s', 'SERIAL1', 'shell', 'input', 'keyevent', '3'])):
            reset_calls()
            core.ejecutar(SPECS[sid], valores, [])
            self.assertEqual(non_devices(calls())[-1], expected, sid)

    def test_unauthorized_segundo_transporte_usa_serial(self):
        scenario('unauth')
        res, cs = self.run_spec('key_back')
        self.assertEqual(cs, [['-s', 'SERIAL1', 'shell', 'input', 'keyevent', '4']])

    def test_scrcpy_flags(self):
        res, cs = self.run_spec('sc_screenoff')
        self.assertTrue(res['success'])
        self.assertEqual(cs, [])


class TestResultados(Base):
    def test_connect_falso_ok(self):
        scenario('connect_fail')
        res, cs = self.run_spec('connect', {'ip': '1.2.3.4:5555'})
        self.assertFalse(res['success'])
        self.assertIn('failed', res['stderr'])
        scenario('default')
        res, cs = self.run_spec('connect', {'ip': '1.2.3.4:5555'})
        self.assertTrue(res['success'])
        self.assertEqual(cs[-1], ['connect', '1.2.3.4:5555'])

    def test_root_produccion(self):
        scenario('root_prod')
        res, cs = self.run_spec('root')
        self.assertFalse(res['success'])
        self.assertIn('producción', res['stderr'])

    def test_list_packages_falla(self):
        scenario('pm_fail')
        res, cs = self.run_spec('pm_list', {'filtro': '-3'})
        self.assertFalse(res['success'])
        self.assertEqual(cs, [['shell', 'pm', 'list', 'packages', '-3']])
        scenario('default')
        res, cs = self.run_spec('pm_list', {'filtro': '-u'})
        self.assertEqual(res['packages'], ['com.example.one', 'com.example.two'])

    def test_processes_y_logcat_fallan_con_adb(self):
        scenario('shell_fail')
        res, cs = self.run_spec('processes')
        self.assertFalse(res['success'])
        res, cs = self.run_spec('logcat_read', {'level': 'V', 'filter': ''})
        self.assertFalse(res['success'])

    def test_debloat_preset_omitidos(self):
        preset = {'id': 'p', 'paquetes': ['com.a.one', 'com.absent', 'com.a.one']}
        res = core.act_debloat_preset(preset)
        self.assertTrue(res['success'])
        self.assertIn('1 desinstalados, 1 ya no estaban, 0 fallos', res['stdout'])
        self.assertEqual(len([c for c in non_devices(calls()) if 'uninstall' in c]), 2)
        res = core.act_debloat_preset({'id': 'p', 'paquetes': ['com.protected']})
        self.assertFalse(res['success'])
        with self.assertRaises(ValueError):
            core.act_debloat_preset({'id': 'p', 'paquetes': 'com.a.b'})

    def test_restore_preset(self):
        res = core.act_restore_preset({'id': 'p', 'paquetes': ['com.a.one']})
        self.assertTrue(res['success'])
        self.assertEqual(non_devices(calls()), [['shell', 'cmd', 'package', 'install-existing', 'com.a.one']])

    def test_mdns_no_soportado(self):
        with mock.patch.object(core, 'run', return_value={'success': True, 'stdout': '', 'stderr': 'adb: mdns is not supported by this version of adb.'}):
            res = core.act_mdns_check()
        self.assertFalse(res['success'])
        self.assertIn('mDNS', res['stderr'])

    def test_device_ip(self):
        res, cs = self.run_spec('device_ip')
        self.assertTrue(res['success'])
        self.assertIn('192.168.1.42', res['stdout'])

    def test_pair(self):
        res, cs = self.run_spec('pair', {'ip': '1.2.3.4:37000', 'code': '123456'})
        self.assertTrue(res['success'])
        self.assertEqual(cs, [['pair', '1.2.3.4:37000', '123456']])


class TestDispositivo(Base):
    def test_devices(self):
        res = core.act_devices()
        self.assertTrue(res['success'])
        self.assertIn('SERIAL1', res['stdout'])

    def test_transports_estados(self):
        scenario('noperm')
        devs, _ = core.list_transports(fresh=True)
        self.assertEqual(devs, [('SERIAL1', 'no permissions')])
        info = core.get_device_info()
        self.assertFalse(info['connected'])
        self.assertIn('udev', info['message'])
        scenario('unauth')
        devs, _ = core.list_transports(fresh=True)
        self.assertEqual(devs[1], ('192.168.1.9:5555', 'unauthorized'))

    def test_device_info(self):
        info = core.get_device_info()
        self.assertTrue(info['connected'])
        self.assertEqual(info['serial'], 'SERIAL1')
        self.assertEqual(info['model'], 'SAMSUNG SM-S928B')
        self.assertEqual(info['battery'], '75%')
        self.assertEqual(info['temperature'], '35.7 °C')
        self.assertEqual(info['voltage'], '4.156 V')
        self.assertEqual(info['health'], 'Bien')
        self.assertEqual(info['battery_status'], 'Cargando')
        self.assertEqual(info['nav_mode'], 'Gestos')
        self.assertEqual(info['secure'], 'Knox 0x0 (Valid)')
        self.assertEqual(info['home_role'], 'com.example.launcher')
        res = core.act_device_info()
        self.assertTrue(res['success'])
        self.assertIn('serial: SERIAL1', res['stdout'])
        self.assertEqual(res['info']['serial'], 'SERIAL1')

    def test_device_info_android13_roles(self):
        scenario('android13')
        info = core.get_device_info()
        self.assertTrue(info['connected'])
        self.assertEqual(info['home_role'], 'com.miui.home')
        self.assertEqual(info['sms_role'], 'com.samsung.android.messaging')

    def test_device_info_sin_knox_prop(self):
        scenario('noknox')
        info = core.get_device_info()
        self.assertEqual(info['secure'], 'Knox N/A')

    def test_device_info_shell_falla(self):
        scenario('shell_fail')
        info = core.get_device_info()
        self.assertFalse(info['connected'])
        self.assertIn('offline', info['message'])

    def test_device_info_sin_dispositivo(self):
        scenario('none')
        info = core.get_device_info()
        self.assertFalse(info['connected'])
        self.assertEqual(info['message'], 'No hay dispositivo ADB conectado')

    def test_refresco_lanza_pocos_procesos(self):
        core.get_device_info()
        cs = calls()
        self.assertLessEqual(len([c for c in cs if c[:1] == ['devices']]), 2)

    def test_nav_mode_map(self):
        self.assertEqual(core._NAV_MODES, {'0': '3 Botones', '1': '2 Botones', '2': 'Gestos'})


class TestBateria(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)

    def _norm(self, text):
        return core._normalize_battery(core._parse_battery_state(text))

    def test_samsung_real(self):
        data = self._norm((FIXTURES / 'battery_samsung_s24.txt').read_text(encoding='utf-8'))
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
"""
        data = self._norm(text)
        self.assertEqual(data['level'], 75)
        self.assertEqual(data['voltage_mv'], 4156)

    def test_escala_y_negativos(self):
        data = self._norm((FIXTURES / 'battery_aosp.txt').read_text(encoding='utf-8'))
        self.assertEqual(data['level'], 80)
        data = self._norm((FIXTURES / 'battery_miui.txt').read_text(encoding='utf-8'))
        self.assertEqual(data['level'], 60)
        self.assertGreaterEqual(data['level'], 0)

    def test_microvoltios_y_centesimas(self):
        data = core._normalize_battery({'level': '50', 'voltage': '4123000', 'temperature': '3570'})
        self.assertEqual(data['voltage_mv'], 4123)
        self.assertEqual(data['temp_tenths'], 357)

    def test_sysfs_temperatura_negativa(self):
        with mock.patch.object(core, 'run_adb', side_effect=lambda args, **kw: {
                'success': True, 'stderr': '',
                'stdout': {'capacity': '40', 'temp': '-35', 'voltage_now': '3900000', 'status': 'Cold', 'health': 'Cold'}
                .get(args[-1].rsplit('/', 1)[-1], '')}):
            data = core._battery_sysfs()
        self.assertEqual(data['temp_tenths'], -35)
        self.assertEqual(data['voltage_mv'], 3900)
        self.assertEqual(data['health'], '7')

    def test_wm_override_prioritario(self):
        self.assertEqual(core._wm_value("Physical size: 1440x3120\nOverride size: 1080x2400", 'size'), '1080x2400')
        self.assertEqual(core._wm_value("Physical size: 1440x3120", 'size'), '1440x3120')
        self.assertEqual(core._wm_value("", 'size'), '')


class TestRun(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)

    def test_bytes_invalidos_no_rompen(self):
        script = os.path.join(TMP, 'bad-utf8')
        Path(script).write_bytes(b'#!/bin/bash\nprintf "ok \\xff\\xfe fin\\n"\n')
        os.chmod(script, 0o755)
        res = core.run([script])
        self.assertTrue(res['success'])
        self.assertIn('fin', res['stdout'])

    def test_timeout_conserva_salida(self):
        script = os.path.join(TMP, 'slow')
        Path(script).write_text('#!/bin/bash\necho parcial\nsleep 5\n')
        os.chmod(script, 0o755)
        res = core.run([script], timeout=1)
        self.assertFalse(res['success'])
        self.assertIn('parcial', res['stdout'])
        self.assertIn('Tiempo agotado', res['stderr'])

    def test_stdin_cerrado(self):
        script = os.path.join(TMP, 'reads-stdin')
        Path(script).write_text('#!/bin/bash\nread -r x; echo "leido:$x"\n')
        os.chmod(script, 0o755)
        t = time.time()
        res = core.run([script], timeout=5)
        self.assertLess(time.time() - t, 3)


class TestCommandWorker(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)
        scenario('default')

    def _wait(self, cond, timeout=5):
        end = time.time() + timeout
        while not cond() and time.time() < end:
            time.sleep(0.02)

    def test_on_done_una_vez(self):
        calls_ = []
        worker = core.CommandWorker(SPECS['devices'], None, None,
                                    on_done=lambda r: calls_.append(('done', r)),
                                    on_error=lambda e: calls_.append(('error', e)))
        worker.start()
        self._wait(lambda: len(calls_) >= 1)
        self.assertEqual(len(calls_), 1)
        self.assertEqual(calls_[0][0], 'done')
        self.assertTrue(calls_[0][1]['success'])

    def test_on_error_solo_excepcion(self):
        calls_ = []
        with mock.patch.object(core, 'ejecutar', side_effect=RuntimeError('boom')):
            worker = core.CommandWorker(SPECS['devices'], None, None,
                                        on_done=lambda r: calls_.append('done'),
                                        on_error=lambda e: calls_.append('error'))
            worker.start()
            self._wait(lambda: len(calls_) >= 1)
        self.assertEqual(calls_, ['error'])

    def test_resultado_fallido_va_a_done(self):
        calls_ = []
        worker = core.CommandWorker({'id': 'x', 'accion': 'no_existe'}, None, None,
                                    on_done=lambda r: calls_.append(('done', r)),
                                    on_error=lambda e: calls_.append('error'))
        worker.start()
        self._wait(lambda: len(calls_) >= 1)
        self.assertEqual(calls_[0][0], 'done')
        self.assertFalse(calls_[0][1]['success'])

    def test_callback_que_falla_no_mata_el_hilo(self):
        def boom(r):
            raise RuntimeError('cb')
        worker = core.CommandWorker(SPECS['devices'], None, None, on_done=boom)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())


class TestConfigYUtilidades(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)
        scenario('default')

    def test_config_roundtrip_y_guardar(self):
        cfg = core.cargar_config()
        self.assertEqual(cfg.get('General', 'theme'), 'system')
        cfg.set('General', 'theme', 'matugen')
        self.assertEqual(core.guardar_config(cfg), '')
        self.assertEqual(core.cargar_config().get('General', 'theme'), 'matugen')

    def test_guardar_config_devuelve_error(self):
        with mock.patch.object(core, 'CONFIG_DIR', Path('/proc/gekko-imposible')), \
                mock.patch.object(core, 'CONFIG_FILE', Path('/proc/gekko-imposible/config.ini')):
            err = core.guardar_config(core.cargar_config())
        self.assertNotEqual(err, '')

    def test_log_desactivado_por_defecto(self):
        core.set_logging(False)
        if core.LOG_FILE.exists():
            core.LOG_FILE.unlink()
        core.log_line('hola')
        self.assertFalse(core.LOG_FILE.exists())
        core.set_logging(True)
        core.log_line('hola')
        self.assertTrue(core.LOG_FILE.exists())
        core.set_logging(False)

    def test_user_dir_fallback_si_xdg_devuelve_home(self):
        fake = {'success': True, 'stdout': str(HOME_FAKE) + '\n', 'stderr': ''}

        class R:
            stdout = str(HOME_FAKE) + '\n'
            returncode = 0
        with mock.patch.object(core.subprocess, 'run', return_value=R()):
            self.assertEqual(core.user_dir('MUSIC'), str(HOME_FAKE / 'Música'))
        with mock.patch.object(core.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(core.user_dir('DOWNLOAD'), str(HOME_FAKE / 'Descargas'))

    def test_cli_version_y_diagnostics(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = core.main(['--version'])
        self.assertEqual(rc, 0)
        self.assertIn(core.APP_VERSION, buf.getvalue())
        with mock.patch.object(core, 'ADB_EXEC', os.path.join(TMP, 'no-adb')), \
                mock.patch.object(core.shutil, 'which', return_value=None):
            text, rc = core.diagnostics()
        self.assertEqual(rc, 1)
        self.assertIn('NO DISPONIBLE', text)

    def test_catalogo_malformado(self):
        bad = Path(TMP) / 'bad.json'
        bad.write_text('{"categorias": [{"id": "x"}]}')
        with mock.patch.object(core, 'CATALOGO_FILE', bad):
            with self.assertRaises(core.CatalogoError):
                core.load_catalogo()
        bad.write_text('{ no json')
        with mock.patch.object(core, 'CATALOGO_FILE', bad):
            with self.assertRaises(core.CatalogoError):
                core.load_catalogo()

    def test_validar_campos(self):
        spec = {'campos': [{'clave': 'a', 'tipo': 'numero', 'etiqueta': 'A'}, {'clave': 'b', 'tipo': 'texto', 'etiqueta': 'B', 'opcional': True}]}
        self.assertEqual(core.validar_campos(spec, {'a': '5', 'b': ''}), [])
        self.assertEqual(core.validar_campos(spec, {'a': '', 'b': ''}), ['Falta el valor: A'])
        self.assertEqual(core.validar_campos(spec, {'a': 'x'}), ['A debe ser un número entero'])


if __name__ == '__main__':
    unittest.main()
