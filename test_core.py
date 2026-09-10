#!/usr/bin/env python3
"""Tests del núcleo headless (sin gi, sin display).

Un `adb` falso registra el argv EXACTO de cada llamada en un archivo, así
cada test afirma el comando real que se envía a adb, no solo 'success'.
El escenario del adb falso (1 dispositivo, 2, sin autorizar, sin
dispositivo, errores) se elige escribiendo un archivo de escenario.
"""
import json
import os
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
SCRCPY_LOG = Path(TMP) / 'scrcpy_argv.log'
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
                # Tal cual responde el móvil real cuando no hay tasa forzada.
                if [[ "${args[2]}" == "get" && "${args[4]}" == *refresh_rate ]]; then echo "null"; fi
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
                # 'cmd game' rechaza las apps que no son juego POR STDOUT y saliendo
                # con código 0: el mensaje es literal el del móvil del usuario.
                if [[ "${args[2]}" == "game" && "$scen" == "game_not_game" ]]; then
                    echo "Package ${args[-1]} is not of game type, to use the game mode commands, it must specify game category in the manifest as android:appCategory=\"game\""
                    exit 0
                fi
                if [[ "${args[2]}" == "appops" && "${args[3]}" == "get" && "$scen" == "appops" ]]; then
                    echo "SYSTEM_ALERT_WINDOW: allow"; echo "RUN_IN_BACKGROUND: ignore"
                fi
                if [[ "${args[2]}" == "display" && "${args[3]}" == "get-brightness" ]]; then echo "42"; fi
                if [[ "${args[2]}" == "netpolicy" && "${args[3]}" == "get" ]]; then echo "Restrict background status: enabled"; fi
                # dexopt fallido: también sale con código 0 y solo se nota en el texto.
                if [[ "${args[2]}" == "package" && "${args[3]}" == "compile" && "$scen" == "compile_fail" ]]; then
                    echo "Error: Package ${args[-1]} not found"; exit 0
                fi
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


FAKE_SCRCPY_SCRIPT = r'''#!/bin/bash
# scrcpy falso: registra el argv en SU PROPIO log (así los tests de adb siguen
# viendo solo llamadas a adb) y responde según el escenario.
#
# Sale al instante, y eso es deliberado: run_scrcpy() espera 1,5 s y, si el
# proceso ya murió con código 0, devuelve _ok('Scrcpy terminó: …') en vez de
# _ok('Scrcpy lanzado: …'). Los tests afirman ese comportamiento real; el
# escenario 'scrcpy_alive' deja el proceso vivo para probar la otra rama sin
# tocar el núcleo.
printf '%s\n' "$(printf '%s\x1f' "$@")" >> "$GEKKO_TEST_SCRCPY_LOG"
scen="$(cat "$GEKKO_TEST_SCENARIO" 2>/dev/null || echo default)"
case "$scen" in
    scrcpy_fail) echo "ERROR: Could not find encoder 'c2.nope.encoder'" >&2; exit 1;;
    scrcpy_alive) sleep 4; exit 0;;
esac
for a in "$@"; do
    case "$a" in
        --list-encoders)
            # El banner sale por stderr y el listado por stdout, como el scrcpy real.
            echo "scrcpy 4.1 <https://github.com/Genymobile/scrcpy>" >&2
            echo "List of video encoders:"
            echo "    --video-codec=h264 --video-encoder=c2.android.avc.encoder"
            echo "    --video-codec=h265 --video-encoder=c2.android.hevc.encoder"
            exit 0;;
        --list-apps)
            echo "scrcpy 4.1 <https://github.com/Genymobile/scrcpy>" >&2
            echo "List of apps:"
            echo " * Ajustes                       [com.android.settings]"
            echo " - Genshin Impact                [com.miHoYo.GenshinImpact]"
            exit 0;;
    esac
done
exit 0
'''


def _write_fake(path, script=FAKE_ADB_SCRIPT):
    Path(path).write_text(script, encoding='utf-8')
    os.chmod(path, 0o755)
    return path


FAKE_ADB = _write_fake(os.path.join(TMP, 'fake-adb'))
FAKE_SCRCPY = _write_fake(os.path.join(TMP, 'fake-scrcpy'), FAKE_SCRCPY_SCRIPT)
os.environ['GEKKO_ADB_EXECUTABLE'] = FAKE_ADB
os.environ['GEKKO_TEST_ARGV_LOG'] = str(ARGV_LOG)
os.environ['GEKKO_TEST_SCRCPY_LOG'] = str(SCRCPY_LOG)
os.environ['GEKKO_TEST_SCENARIO'] = str(SCENARIO)
os.environ['GEKKO_TEST_FIXTURES'] = str(FIXTURES)
os.environ['GEKKO_SCRCPY_EXECUTABLE'] = FAKE_SCRCPY
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
        # El separador va SIEMPRE al final, así que se quita solo ese con [:-1].
        # Filtrar todos los vacíos borraría también los argumentos vacíos INTERIORES,
        # que es justo la regresión que estos tests vigilan (p. ej. un '--fps ''').
        out.append(line.split('\x1f')[:-1])
    return out


def reset_calls():
    if ARGV_LOG.exists():
        ARGV_LOG.unlink()
    core.invalidate_transports()


def non_devices(cs):
    return [c for c in cs if c[:1] != ['devices'] and c[:3] != ['devices', '-l']]


def scrcpy_calls():
    """Lista de argv (listas) registrados por el scrcpy falso desde el último reset."""
    if not SCRCPY_LOG.exists():
        return []
    # Igual que calls(): [:-1] quita el separador final y conserva los vacíos interiores.
    return [line.split('\x1f')[:-1]
            for line in SCRCPY_LOG.read_text(encoding='utf-8').splitlines()]


def reset_scrcpy_calls():
    if SCRCPY_LOG.exists():
        SCRCPY_LOG.unlink()


class Base(unittest.TestCase):
    def setUp(self):
        os.environ.update(ENV)
        scenario('default')
        reset_calls()
        reset_scrcpy_calls()

    def run_spec(self, spec_id, valores=None, flags=None):
        res = core.ejecutar(SPECS[spec_id], valores or {}, flags or [])
        return res, non_devices(calls())

    def run_scrcpy_spec(self, spec_id, valores=None):
        """Como run_spec pero devuelve el argv que recibió el scrcpy falso."""
        res = core.ejecutar(SPECS[spec_id], valores or {}, [])
        return res, scrcpy_calls()

    def defectos(self, spec_id):
        """Los valores que la UI enviaría sin que el usuario toque nada."""
        return {c['clave']: c.get('defecto', '') for c in SPECS[spec_id].get('campos') or []}


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
        # Antes solo afirmaba que no se llamó a adb; con el scrcpy falso también
        # se comprueba la bandera real y el mensaje del proceso que ya terminó.
        res, cs = self.run_spec('sc_screenoff')
        self.assertTrue(res['success'])
        self.assertEqual(cs, [])
        self.assertEqual(scrcpy_calls(), [['--turn-screen-off']])
        self.assertIn('Scrcpy terminó: --turn-screen-off', res['stdout'])


class TestGaming(Base):
    """Sección Gaming: cada botón afirma el argv EXACTO que recibe scrcpy.

    Todo el valor de esta sección está en las banderas, así que aquí no basta
    con `success`: el scrcpy falso registra su argv y cada test lo compara
    entero, con y sin campos opcionales rellenos.
    """

    KBM = ['-m', '1080', '-b', '9M', '--video-codec=h264', '--keyboard=uhid', '--mouse=uhid']

    # ---- catálogo ----------------------------------------------------
    def test_categoria_gaming_completa(self):
        cats = [k for k in CAT['categorias'] if k['id'] == 'gaming']
        self.assertEqual(len(cats), 1, 'falta la categoría gaming')
        self.assertEqual([c['id'] for c in cats[0]['comandos']],
                         ['game_kbm', 'game_pad', 'game_virtual', 'game_otg',
                          'game_lowlat', 'game_encoders', 'game_apps', 'game_kbd_layout'])

    # ---- el botón estrella -------------------------------------------
    def test_game_kbm_defectos_reproduce_el_comando_del_usuario(self):
        """Con los defectos sale exactamente el comando que el usuario ya usaba."""
        res, sc = self.run_scrcpy_spec('game_kbm', self.defectos('game_kbm'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [self.KBM])
        # El scrcpy falso muere al instante: run_scrcpy ve returncode 0.
        self.assertIn('Scrcpy terminó: ' + ' '.join(self.KBM), res['stdout'])
        self.assertEqual(non_devices(calls()), [], 'gaming no debe llamar a adb')

    def test_game_kbm_codificador_relleno(self):
        v = dict(self.defectos('game_kbm'), encoder='c2.android.avc.encoder')
        res, sc = self.run_scrcpy_spec('game_kbm', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-m', '1080', '-b', '9M', '--video-codec=h264',
                               '--video-encoder=c2.android.avc.encoder',
                               '--keyboard=uhid', '--mouse=uhid']])

    def test_game_kbm_codificador_y_fps_vacios_no_generan_bandera(self):
        """Un campo opcional vacío (o con espacios) no deja un '--video-encoder=' colgando."""
        v = dict(self.defectos('game_kbm'), encoder='   ', max_fps='')
        res, sc = self.run_scrcpy_spec('game_kbm', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [self.KBM])
        self.assertNotIn('--video-encoder', ' '.join(sc[0]))
        self.assertNotIn('--max-fps', ' '.join(sc[0]))

    def test_game_kbm_fps_pantalla_completa_y_apagar_pantalla(self):
        v = dict(self.defectos('game_kbm'), max_fps='60', fullscreen='1', screen_off='1')
        res, sc = self.run_scrcpy_spec('game_kbm', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-m', '1080', '-b', '9M', '--video-codec=h264', '--max-fps=60',
                               '--fullscreen', '--turn-screen-off',
                               '--keyboard=uhid', '--mouse=uhid']])

    def test_game_kbm_dos_dispositivos_antepone_serial(self):
        scenario('two')
        res, sc = self.run_scrcpy_spec('game_kbm', self.defectos('game_kbm'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-s', 'SERIAL1'] + self.KBM])

    def test_game_kbm_codec_alternativo(self):
        v = dict(self.defectos('game_kbm'), codec='h265')
        res, sc = self.run_scrcpy_spec('game_kbm', v)
        self.assertEqual(sc[0][4], '--video-codec=h265')

    # ---- mando --------------------------------------------------------
    def test_game_pad_defectos_y_aoa(self):
        res, sc = self.run_scrcpy_spec('game_pad', self.defectos('game_pad'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [self.KBM + ['--gamepad=uhid']])
        reset_scrcpy_calls()
        v = dict(self.defectos('game_pad'), gamepad='aoa')
        res, sc = self.run_scrcpy_spec('game_pad', v)
        self.assertEqual(sc, [self.KBM + ['--gamepad=aoa']])

    # ---- pantalla virtual ---------------------------------------------
    def test_game_virtual_defectos(self):
        res, sc = self.run_scrcpy_spec('game_virtual', self.defectos('game_virtual'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-b', '9M', '--video-codec=h264', '--new-display=1920x1080',
                               '--keyboard=uhid', '--mouse=uhid']])

    def test_game_virtual_sin_resolucion_usa_new_display_a_secas(self):
        v = dict(self.defectos('game_virtual'), new_display='')
        res, sc = self.run_scrcpy_spec('game_virtual', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-b', '9M', '--video-codec=h264', '--new-display',
                               '--keyboard=uhid', '--mouse=uhid']])

    def test_game_virtual_con_dpi_app_y_mando(self):
        v = dict(self.defectos('game_virtual'), new_display='1920x1080/420',
                 package='com.miHoYo.GenshinImpact', gamepad='uhid', max_fps='90')
        res, sc = self.run_scrcpy_spec('game_virtual', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-b', '9M', '--video-codec=h264', '--max-fps=90',
                               '--new-display=1920x1080/420',
                               '--start-app=com.miHoYo.GenshinImpact',
                               '--keyboard=uhid', '--mouse=uhid', '--gamepad=uhid']])

    def test_game_virtual_busqueda_por_nombre_de_app(self):
        """'?' busca por nombre aproximado y '+' fuerza detener la app antes."""
        for valor in ('?Genshin', '+?Genshin'):
            reset_scrcpy_calls()
            v = dict(self.defectos('game_virtual'), package=valor)
            res, sc = self.run_scrcpy_spec('game_virtual', v)
            self.assertTrue(res['success'], res['stderr'])
            self.assertIn(f'--start-app={valor}', sc[0])

    # ---- OTG -----------------------------------------------------------
    def test_game_otg_defectos_y_sin_mando(self):
        res, sc = self.run_scrcpy_spec('game_otg', self.defectos('game_otg'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['--otg', '--keyboard=aoa', '--mouse=aoa', '--gamepad=aoa']])
        reset_scrcpy_calls()
        res, sc = self.run_scrcpy_spec('game_otg', {'gamepad': ''})
        self.assertEqual(sc, [['--otg', '--keyboard=aoa', '--mouse=aoa']])

    def test_game_otg_no_lleva_banderas_de_video(self):
        """En OTG no hay vídeo: -m, -b y --video-codec no deben aparecer."""
        _, sc = self.run_scrcpy_spec('game_otg', self.defectos('game_otg'))
        argv = sc[0]
        for bandera in ('-m', '-b'):
            self.assertNotIn(bandera, argv)
        for prefijo in ('--video-codec', '--new-display', '--max-fps', '--video-buffer'):
            self.assertEqual([a for a in argv if a.startswith(prefijo)], [], prefijo)

    # ---- latencia mínima -----------------------------------------------
    def test_game_lowlat_defectos(self):
        res, sc = self.run_scrcpy_spec('game_lowlat', self.defectos('game_lowlat'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-m', '720', '-b', '4M', '--video-codec=h264', '--max-fps=60',
                               '--video-buffer=0', '--no-audio',
                               '--keyboard=uhid', '--mouse=uhid']])
        # --display-buffer no existe desde scrcpy 3.0: nunca debe salir.
        self.assertNotIn('--display-buffer', ' '.join(sc[0]))

    # ---- valores inválidos ---------------------------------------------
    def _rechaza(self, spec_id, valores, trozo):
        res, sc = self.run_scrcpy_spec(spec_id, valores)
        self.assertFalse(res['success'], f'{trozo}: debería fallar')
        self.assertIn(trozo, res['stderr'])
        self.assertEqual(sc, [], 'no se debe lanzar scrcpy con un valor inválido')

    def test_bitrate_invalido(self):
        for malo in ('9 megas', '9MB', '-9M', '9M;rm', ''):
            reset_scrcpy_calls()
            v = dict(self.defectos('game_kbm'), bitrate=malo)
            trozo = 'Falta el valor' if malo == '' else 'Bitrate no válido'
            self._rechaza('game_kbm', v, trozo)

    def test_codificador_con_caracteres_extranos(self):
        for malo in ('c2.android; rm -rf ~', 'c2 android', '-c2.android', 'c2/android'):
            reset_scrcpy_calls()
            v = dict(self.defectos('game_kbm'), encoder=malo)
            self._rechaza('game_kbm', v, 'Codificador no válido')

    def test_resolucion_no_numerica_y_negativa(self):
        v = dict(self.defectos('game_kbm'), max_size='mucha')
        self._rechaza('game_kbm', v, 'debe ser un número entero')
        reset_scrcpy_calls()
        v = dict(self.defectos('game_kbm'), max_size='-5')
        self._rechaza('game_kbm', v, 'no puede ser negativo')

    def test_pantalla_virtual_invalida(self):
        for malo in ('1920*1080', '1920x', 'grande', '/'):
            reset_scrcpy_calls()
            v = dict(self.defectos('game_virtual'), new_display=malo)
            self._rechaza('game_virtual', v, 'Pantalla virtual no válida')

    def test_paquete_invalido_en_pantalla_virtual(self):
        v = dict(self.defectos('game_virtual'), package='no es un paquete')
        self._rechaza('game_virtual', v, 'Paquete no válido')

    def test_codec_y_mando_fuera_de_lista(self):
        v = dict(self.defectos('game_kbm'), codec='h266')
        self._rechaza('game_kbm', v, 'Códec de vídeo no válido')
        reset_scrcpy_calls()
        v = dict(self.defectos('game_pad'), gamepad='sdk')
        self._rechaza('game_pad', v, 'Mando no válido')

    def test_campo_obligatorio_vacio(self):
        v = dict(self.defectos('game_lowlat'), video_buffer='')
        self._rechaza('game_lowlat', v, 'Falta el valor: Búfer de vídeo')

    def test_modo_de_gaming_desconocido(self):
        with self.assertRaises(ValueError) as ctx:
            core.scrcpy_game_args({'mode': 'consola'})
        self.assertIn('Modo de gaming desconocido', str(ctx.exception))
        self.assertEqual(scrcpy_calls(), [])

    # ---- listados (salida capturada) ------------------------------------
    def test_listar_codificadores_devuelve_la_salida(self):
        res, sc = self.run_scrcpy_spec('game_encoders')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['--list-encoders']])
        self.assertIn('c2.android.avc.encoder', res['stdout'])
        # stderr (banner) primero, stdout (listado) después.
        self.assertLess(res['stdout'].index('scrcpy 4.1'),
                        res['stdout'].index('List of video encoders'))

    def test_listar_apps_devuelve_los_paquetes(self):
        res, sc = self.run_scrcpy_spec('game_apps')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['--list-apps']])
        self.assertIn('com.miHoYo.GenshinImpact', res['stdout'])

    def test_listados_con_dos_dispositivos_usan_serial(self):
        scenario('two')
        res, sc = self.run_scrcpy_spec('game_encoders')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(sc, [['-s', 'SERIAL1', '--list-encoders']])

    def test_listado_desconocido(self):
        res = core.act_scrcpy_list('lunas')
        self.assertFalse(res['success'])
        self.assertIn('Listado de scrcpy desconocido', res['stderr'])
        self.assertEqual(scrcpy_calls(), [])

    def test_listado_que_falla_devuelve_stderr(self):
        scenario('scrcpy_fail')
        res, sc = self.run_scrcpy_spec('game_encoders')
        self.assertFalse(res['success'])
        self.assertIn('Could not find encoder', res['stderr'])
        self.assertEqual(sc, [['--list-encoders']])

    # ---- ramas de run_scrcpy --------------------------------------------
    def test_scrcpy_que_muere_al_arrancar_es_un_fallo(self):
        scenario('scrcpy_fail')
        res, sc = self.run_scrcpy_spec('game_kbm', self.defectos('game_kbm'))
        self.assertFalse(res['success'])
        self.assertIn('Could not find encoder', res['stderr'])
        self.assertEqual(sc, [self.KBM])

    def test_scrcpy_que_sigue_vivo_se_da_por_lanzado(self):
        """Si sobrevive a los 1,5 s de run_scrcpy, el mensaje es 'Scrcpy lanzado'.

        run_scrcpy() lanza desacoplado y no devuelve el proceso, así que aquí se
        espía Popen solo para poder matar al falso al terminar (si no, queda un
        `sleep` suelto y Python avisa de un subproceso sin recoger).
        """
        scenario('scrcpy_alive')
        procesos = []
        popen_real = core.subprocess.Popen

        def espia(*a, **kw):
            proc = popen_real(*a, **kw)
            procesos.append(proc)
            return proc

        self.addCleanup(self._matar, procesos)
        with mock.patch.object(core.subprocess, 'Popen', espia):
            res, sc = self.run_scrcpy_spec('game_kbm', self.defectos('game_kbm'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertIn('Scrcpy lanzado: ' + ' '.join(self.KBM), res['stdout'])
        self.assertEqual(sc, [self.KBM])

    @staticmethod
    def _matar(procesos):
        for proc in procesos:
            try:
                proc.kill()
                proc.wait(timeout=5)
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

    # ---- teclado físico --------------------------------------------------
    def test_configurar_teclado_fisico_usa_adb(self):
        """El botón del teclado físico no es scrcpy: abre los ajustes por adb."""
        res, cs = self.run_spec('game_kbd_layout')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'am', 'start', '-a',
                               'android.settings.HARD_KEYBOARD_SETTINGS']])
        self.assertEqual(scrcpy_calls(), [])


class TestRendimiento(Base):
    """Sección «Rendimiento y Juegos»: argv exacto de cada botón.

    Aquí no hay banderas de scrcpy sino comandos del móvil, así que cada test
    compara la lista completa que recibe el adb falso. La trampa gorda de
    'cmd game' (solo acepta apps declaradas como juego, y el rechazo sale por
    stdout CON código 0) tiene su propio escenario.
    """

    JUEGO = 'com.miHoYo.GenshinImpact'
    # Valores que ninguna validación debe dejar pasar a adb.
    HOSTILES = ('com.x; id', 'com.x $(id)', '--otra-bandera', 'com.x rm -rf ~',
                'com. x', 'com.x&&reboot')

    def _rechaza(self, spec_id, valores, trozo):
        """El botón falla con un error claro y NO llega nada a adb."""
        res, cs = self.run_spec(spec_id, valores)
        self.assertFalse(res['success'], f'{trozo}: debería fallar')
        self.assertIn(trozo, res['stderr'])
        self.assertEqual(cs, [], 'no se debe llamar a adb con un valor inválido')

    # ---- catálogo ------------------------------------------------------
    def test_categoria_rendimiento_completa(self):
        cats = [k for k in CAT['categorias'] if k['id'] == 'rendimiento']
        self.assertEqual(len(cats), 1, 'falta la categoría rendimiento')
        self.assertEqual([c['id'] for c in cats[0]['comandos']],
                         ['perf_game_mode', 'perf_game_modes', 'perf_game_configs',
                          'perf_game_set', 'perf_game_reset', 'perf_refresh_get',
                          'perf_refresh_put', 'perf_refresh_reset', 'perf_gfxinfo',
                          'perf_thermal', 'perf_compile', 'perf_compile_reset'])

    def test_todos_los_botones_de_cmd_game_avisan_de_la_trampa(self):
        """Un botón de 'cmd game' sin el aviso parecerá roto con una app normal."""
        juegos = [c for c in SPECS.values()
                  if c.get('accion') in ('game_mode', 'game_list', 'game_set', 'game_reset')]
        self.assertEqual(len(juegos), 5)
        for spec in juegos:
            self.assertIn('appCategory', spec.get('advertencia', ''), spec['id'])

    # ---- cmd game mode --------------------------------------------------
    def test_game_mode_argv(self):
        res, cs = self.run_spec('perf_game_mode', {'mode': 'performance', 'package': self.JUEGO})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'game', 'mode', 'performance', self.JUEGO]])

    def test_game_mode_los_tres_modos(self):
        for modo in ('standard', 'performance', 'battery'):
            reset_calls()
            res, cs = self.run_spec('perf_game_mode', {'mode': modo, 'package': self.JUEGO})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'game', 'mode', modo, self.JUEGO]])

    def test_game_mode_defectos_piden_el_paquete(self):
        """El paquete viene vacío a propósito: sin él la app no debe inventarse nada."""
        self._rechaza('perf_game_mode', self.defectos('perf_game_mode'), 'Falta el valor')

    def test_game_mode_dos_dispositivos_antepone_serial(self):
        scenario('two')
        res, cs = self.run_spec('perf_game_mode', {'mode': 'performance', 'package': self.JUEGO})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['-s', 'SERIAL1', 'shell', 'cmd', 'game', 'mode',
                               'performance', self.JUEGO]])

    def test_game_mode_modo_fuera_de_lista(self):
        self._rechaza('perf_game_mode', {'mode': 'turbo', 'package': self.JUEGO},
                      'modo de juego no válido')

    def test_game_mode_paquetes_hostiles(self):
        for malo in self.HOSTILES:
            reset_calls()
            self._rechaza('perf_game_mode', {'mode': 'performance', 'package': malo},
                          'Nombre de paquete no válido')

    # ---- listados de cmd game -------------------------------------------
    def test_game_list_modes_y_configs(self):
        for spec_id, sub in (('perf_game_modes', 'list-modes'),
                             ('perf_game_configs', 'list-configs')):
            reset_calls()
            res, cs = self.run_spec(spec_id, {'package': self.JUEGO})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'game', sub, self.JUEGO]])

    def test_game_list_desconocido(self):
        res = core.act_game_list('nada', self.JUEGO)
        self.assertFalse(res['success'])
        self.assertIn('Listado de modo de juego desconocido', res['stderr'])
        self.assertEqual(non_devices(calls()), [])

    def test_game_reset_argv(self):
        res, cs = self.run_spec('perf_game_reset', {'package': self.JUEGO})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'game', 'reset', self.JUEGO]])

    # ---- cmd game set (campos opcionales) --------------------------------
    def test_game_set_defectos_solo_reescalado(self):
        v = dict(self.defectos('perf_game_set'), package=self.JUEGO)
        res, cs = self.run_spec('perf_game_set', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'game', 'set', '--downscale', '0.75', self.JUEGO]])

    def test_game_set_solo_fps(self):
        """El campo vacío no debe dejar un '--downscale' sin valor detrás."""
        v = {'downscale': '', 'fps': '60', 'package': self.JUEGO}
        res, cs = self.run_spec('perf_game_set', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'game', 'set', '--fps', '60', self.JUEGO]])
        self.assertNotIn('--downscale', cs[0])

    def test_game_set_los_dos_ajustes_y_el_paquete_al_final(self):
        v = {'downscale': '0.5', 'fps': '0', 'package': self.JUEGO}
        res, cs = self.run_spec('perf_game_set', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'game', 'set', '--downscale', '0.5',
                               '--fps', '0', self.JUEGO]])

    def test_game_set_sin_ningun_ajuste_no_llama_a_adb(self):
        v = {'downscale': '', 'fps': '', 'package': self.JUEGO}
        self._rechaza('perf_game_set', v, 'Indica al menos un ajuste')

    def test_game_set_fps_negativo_y_no_numerico(self):
        v = {'downscale': '', 'fps': '-30', 'package': self.JUEGO}
        self._rechaza('perf_game_set', v, 'no puede ser negativo')
        reset_calls()
        v = {'downscale': '', 'fps': 'sesenta', 'package': self.JUEGO}
        self._rechaza('perf_game_set', v, 'debe ser un número entero')

    def test_game_set_reescalado_fuera_de_lista(self):
        v = {'downscale': '0.99', 'fps': '', 'package': self.JUEGO}
        self._rechaza('perf_game_set', v, 'reescalado no válido')

    # ---- la trampa: la app no es un juego ---------------------------------
    def test_app_que_no_es_juego_se_marca_como_error(self):
        """El móvil contesta por stdout y SALE CON 0: sin leerlo parecería un éxito."""
        scenario('game_not_game')
        casos = [('perf_game_mode', {'mode': 'performance', 'package': 'com.android.settings'}),
                 ('perf_game_modes', {'package': 'com.android.settings'}),
                 ('perf_game_configs', {'package': 'com.android.settings'}),
                 ('perf_game_reset', {'package': 'com.android.settings'}),
                 ('perf_game_set', {'downscale': '0.5', 'fps': '', 'package': 'com.android.settings'})]
        for spec_id, valores in casos:
            reset_calls()
            res, cs = self.run_spec(spec_id, valores)
            self.assertFalse(res['success'], f'{spec_id} debería marcarse como error')
            self.assertIn('is not of game type', res['stderr'])
            self.assertIn('android:appCategory="game"', res['stderr'])
            self.assertEqual(len(cs), 1, spec_id)

    # ---- tasa de refresco --------------------------------------------------
    def test_refresh_get_lee_las_dos_claves(self):
        res, cs = self.run_spec('perf_refresh_get')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'settings', 'get', 'system', 'min_refresh_rate'],
                              ['shell', 'settings', 'get', 'system', 'peak_refresh_rate']])
        self.assertEqual(res['stdout'], 'min_refresh_rate: null\npeak_refresh_rate: null')

    def test_refresh_put_escribe_las_dos_claves(self):
        res, cs = self.run_spec('perf_refresh_put', self.defectos('perf_refresh_put'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'settings', 'put', 'system', 'min_refresh_rate', '120'],
                              ['shell', 'settings', 'put', 'system', 'peak_refresh_rate', '120']])
        self.assertIn('Para volver al automático', res['stdout'])

    def test_refresh_put_dos_dispositivos(self):
        scenario('two')
        res, cs = self.run_spec('perf_refresh_put', {'hz': '60'})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['-s', 'SERIAL1', 'shell', 'settings', 'put', 'system',
                               'min_refresh_rate', '60'],
                              ['-s', 'SERIAL1', 'shell', 'settings', 'put', 'system',
                               'peak_refresh_rate', '60']])

    def test_refresh_reset_borra_y_no_escribe_numero(self):
        """Restablecer es BORRAR: escribir un número «por defecto» dejaría otra tasa clavada."""
        res, cs = self.run_spec('perf_refresh_reset')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'settings', 'delete', 'system', 'min_refresh_rate'],
                              ['shell', 'settings', 'delete', 'system', 'peak_refresh_rate']])

    def test_refresh_put_valores_malos(self):
        self._rechaza('perf_refresh_put', {'hz': '500'}, 'fuera de rango')
        reset_calls()
        self._rechaza('perf_refresh_put', {'hz': '0'}, 'fuera de rango')
        reset_calls()
        self._rechaza('perf_refresh_put', {'hz': '-60'}, 'no puede ser negativo')
        reset_calls()
        self._rechaza('perf_refresh_put', {'hz': '120 Hz'}, 'debe ser un número entero')
        reset_calls()
        self._rechaza('perf_refresh_put', {'hz': ''}, 'Falta el valor')

    def test_refresh_operacion_desconocida(self):
        res = core.act_refresh_rate('borrar')
        self.assertFalse(res['success'])
        self.assertIn('Operación de tasa de refresco desconocida', res['stderr'])
        self.assertEqual(non_devices(calls()), [])

    def test_refresh_put_que_falla_se_marca_como_error(self):
        scenario('settings_fail')
        res, cs = self.run_spec('perf_refresh_put', {'hz': '120'})
        self.assertFalse(res['success'])
        self.assertIn('settings falló en alguna de las dos claves', res['stderr'])
        self.assertEqual(len(cs), 2, 'las dos claves se intentan igual')

    # ---- gfxinfo y estado térmico -------------------------------------------
    def test_gfxinfo_argv(self):
        res, cs = self.run_spec('perf_gfxinfo', {'package': self.JUEGO})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'dumpsys', 'gfxinfo', self.JUEGO]])

    def test_gfxinfo_paquetes_hostiles(self):
        for malo in self.HOSTILES:
            reset_calls()
            self._rechaza('perf_gfxinfo', {'package': malo}, 'Nombre de paquete no válido')

    def test_gfxinfo_servicio_hostil(self):
        """El servicio sale del catálogo, pero la función lo valida igual."""
        res = core.act_dumpsys_app('gfxinfo; id', self.JUEGO)
        self.assertFalse(res['success'])
        self.assertIn('Servicio no válido', res['stderr'])
        self.assertEqual(non_devices(calls()), [])

    def test_thermal_argv(self):
        res, cs = self.run_spec('perf_thermal')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'dumpsys', 'thermalservice']])

    # ---- dexopt --------------------------------------------------------------
    def test_compile_defectos(self):
        v = dict(self.defectos('perf_compile'), package=self.JUEGO)
        res, cs = self.run_spec('perf_compile', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'package', 'compile', '-m', 'speed',
                               '-f', self.JUEGO]])

    def test_compile_los_tres_filtros(self):
        for filtro in ('speed', 'speed-profile', 'verify'):
            reset_calls()
            res, cs = self.run_spec('perf_compile', {'filtro': filtro, 'package': self.JUEGO})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'package', 'compile', '-m', filtro,
                                   '-f', self.JUEGO]])

    def test_compile_filtro_fuera_de_lista(self):
        self._rechaza('perf_compile', {'filtro': 'everything', 'package': self.JUEGO},
                      'filtro de compilación no válido')

    def test_compile_reset_argv(self):
        res, cs = self.run_spec('perf_compile_reset', {'package': self.JUEGO})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'package', 'compile', '--reset', self.JUEGO]])

    def test_compile_error_con_codigo_0_se_marca_como_fallo(self):
        scenario('compile_fail')
        res, cs = self.run_spec('perf_compile', {'filtro': 'speed', 'package': self.JUEGO})
        self.assertFalse(res['success'])
        self.assertIn('not found', res['stderr'])
        self.assertEqual(len(cs), 1)


class TestPermisosPantallaYRed(Base):
    """Botones nuevos de Apps, Pantalla, Red y Diagnóstico: argv exacto."""

    PKG = 'com.example.app'
    HOSTILES = TestRendimiento.HOSTILES

    def _rechaza(self, spec_id, valores, trozo):
        res, cs = self.run_spec(spec_id, valores)
        self.assertFalse(res['success'], f'{trozo}: debería fallar')
        self.assertIn(trozo, res['stderr'])
        self.assertEqual(cs, [], 'no se debe llamar a adb con un valor inválido')

    # ---- appops -----------------------------------------------------------
    def test_appops_get_sin_operacion(self):
        res, cs = self.run_spec('pm_appops_get', {'package': self.PKG, 'op': ''})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'appops', 'get', self.PKG]])
        self.assertIn('sin operaciones registradas', res['stdout'])

    def test_appops_get_operacion_vacia_o_con_espacios_no_anade_argumento(self):
        res, cs = self.run_spec('pm_appops_get', {'package': self.PKG, 'op': '   '})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'appops', 'get', self.PKG]])

    def test_appops_get_con_operacion(self):
        for op in ('SYSTEM_ALERT_WINDOW', 'android:coarse_location'):
            reset_calls()
            res, cs = self.run_spec('pm_appops_get', {'package': self.PKG, 'op': op})
            self.assertTrue(res['success'], res['stderr'])
            # La operación llega como UN solo argumento, sin partirse ni citarse.
            self.assertEqual(cs, [['shell', 'cmd', 'appops', 'get', self.PKG, op]])

    def test_appops_get_devuelve_la_salida_tal_cual(self):
        scenario('appops')
        res, cs = self.run_spec('pm_appops_get', {'package': self.PKG, 'op': ''})
        self.assertTrue(res['success'], res['stderr'])
        self.assertIn('SYSTEM_ALERT_WINDOW: allow', res['stdout'])
        self.assertNotIn('sin operaciones registradas', res['stdout'])

    def test_appops_get_dos_dispositivos(self):
        scenario('two')
        res, cs = self.run_spec('pm_appops_get', {'package': self.PKG, 'op': ''})
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['-s', 'SERIAL1', 'shell', 'cmd', 'appops', 'get', self.PKG]])

    def test_appops_set_defectos(self):
        v = dict(self.defectos('pm_appops_set'), package=self.PKG)
        res, cs = self.run_spec('pm_appops_set', v)
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'appops', 'set', self.PKG,
                               'SYSTEM_ALERT_WINDOW', 'allow']])

    def test_appops_set_los_cuatro_modos(self):
        for modo in ('allow', 'ignore', 'deny', 'default'):
            reset_calls()
            res, cs = self.run_spec('pm_appops_set', {'package': self.PKG,
                                                      'op': 'RUN_IN_BACKGROUND', 'mode': modo})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'appops', 'set', self.PKG,
                                   'RUN_IN_BACKGROUND', modo]])

    def test_appops_set_modo_fuera_de_lista(self):
        self._rechaza('pm_appops_set', {'package': self.PKG, 'op': 'RUN_IN_BACKGROUND',
                                        'mode': 'siempre'}, 'modo no válido')

    def test_appops_operaciones_hostiles(self):
        for malo in ('RUN IN BACKGROUND', 'OP; id', '$(id)', '--otra-bandera', '1OP'):
            reset_calls()
            self._rechaza('pm_appops_set', {'package': self.PKG, 'op': malo, 'mode': 'allow'},
                          'Operación de appops no válida')

    def test_appops_paquetes_hostiles(self):
        for malo in self.HOSTILES:
            reset_calls()
            self._rechaza('pm_appops_set', {'package': malo, 'op': 'RUN_IN_BACKGROUND',
                                            'mode': 'allow'}, 'Nombre de paquete no válido')

    # ---- brillo -------------------------------------------------------------
    def test_brillo_get(self):
        res, cs = self.run_spec('brightness_get')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'display', 'get-brightness',
                               '--unit', 'percentage']])
        self.assertEqual(res['stdout'], 'Brillo actual: 42 %')

    def test_brillo_set_defectos(self):
        res, cs = self.run_spec('brightness_set', self.defectos('brightness_set'))
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['shell', 'cmd', 'display', 'set-brightness', '50',
                               '--unit', 'percentage']])
        self.assertIn('Brillo fijado al 50 %', res['stdout'])

    def test_brillo_extremos_validos(self):
        for nivel in ('0', '100'):
            reset_calls()
            res, cs = self.run_spec('brightness_set', {'nivel': nivel})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs[0][4], nivel)

    def test_brillo_valores_malos(self):
        self._rechaza('brightness_set', {'nivel': '150'}, 'El brillo va de 0 a 100 %')
        reset_calls()
        self._rechaza('brightness_set', {'nivel': '-10'}, 'no puede ser negativo')
        reset_calls()
        self._rechaza('brightness_set', {'nivel': 'medio'}, 'debe ser un número entero')
        reset_calls()
        self._rechaza('brightness_set', {'nivel': ''}, 'Falta el valor')

    def test_brillo_dos_dispositivos(self):
        scenario('two')
        res, cs = self.run_spec('brightness_get')
        self.assertTrue(res['success'], res['stderr'])
        self.assertEqual(cs, [['-s', 'SERIAL1', 'shell', 'cmd', 'display', 'get-brightness',
                               '--unit', 'percentage']])

    # ---- netpolicy ------------------------------------------------------------
    def test_netpolicy_cada_consulta(self):
        esperado = {'status': ['get', 'restrict-background'],
                    'blacklist': ['list', 'restrict-background-blacklist'],
                    'whitelist': ['list', 'restrict-background-whitelist'],
                    'wifi': ['list', 'wifi-networks']}
        for what, cola in esperado.items():
            reset_calls()
            res, cs = self.run_spec('net_policy', {'what': what})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'netpolicy'] + cola])

    def test_netpolicy_lista_vacia_lo_dice(self):
        res, _ = self.run_spec('net_policy', {'what': 'blacklist'})
        self.assertEqual(res['stdout'], '(lista vacía)')

    def test_netpolicy_status_devuelve_la_salida(self):
        res, _ = self.run_spec('net_policy', {'what': 'status'})
        self.assertIn('Restrict background status', res['stdout'])

    def test_netpolicy_consulta_desconocida(self):
        res = core.act_netpolicy('todo')
        self.assertFalse(res['success'])
        self.assertIn('Consulta de netpolicy desconocida', res['stderr'])
        self.assertEqual(non_devices(calls()), [])

    def test_netpolicy_restrict_true_y_false(self):
        for estado in ('true', 'false'):
            reset_calls()
            res, cs = self.run_spec('net_restrict_set', {'estado': estado})
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['shell', 'cmd', 'netpolicy', 'set',
                                   'restrict-background', estado]])
            self.assertIn(f'restrict-background): {estado}', res['stdout'])

    def test_netpolicy_restrict_valores_malos(self):
        for malo in ('sí', '1', 'true; id', ''):
            reset_calls()
            trozo = 'Falta el valor' if malo == '' else 'estado no válido'
            self._rechaza('net_restrict_set', {'estado': malo}, trozo)

    # ---- botones de lectura sin campos ------------------------------------------
    def test_lecturas_nuevas_argv(self):
        esperado = {'pm_users': ['shell', 'pm', 'list', 'users'],
                    'dismiss_keyguard': ['shell', 'wm', 'dismiss-keyguard'],
                    'db_deviceidle': ['shell', 'dumpsys', 'deviceidle'],
                    'db_batterystats': ['shell', 'dumpsys', 'batterystats'],
                    'db_uptime': ['shell', 'uptime'],
                    'db_services': ['shell', 'service', 'list']}
        for spec_id, argv in esperado.items():
            reset_calls()
            res, cs = self.run_spec(spec_id)
            self.assertTrue(res['success'], f'{spec_id}: {res["stderr"]}')
            self.assertEqual(cs, [argv], spec_id)

    def test_lecturas_nuevas_con_dos_dispositivos(self):
        scenario('two')
        for spec_id, argv in (('pm_users', ['shell', 'pm', 'list', 'users']),
                              ('db_uptime', ['shell', 'uptime']),
                              ('db_services', ['shell', 'service', 'list'])):
            reset_calls()
            res, cs = self.run_spec(spec_id)
            self.assertTrue(res['success'], res['stderr'])
            self.assertEqual(cs, [['-s', 'SERIAL1'] + argv], spec_id)


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


class TestValidacionCatalogo(Base):
    """La validación al cargar: es lo que impide que vuelvan los botones rotos
    de fábrica (un select obligatorio con opción vacía siempre daba «Falta el
    valor», y así estuvieron «Reconectar» y «Listar paquetes → Instaladas»)."""

    def _cargar(self, mutar):
        import copy
        with open(PROJECT_DIR / 'adb_commands.json', encoding='utf-8') as f:
            d = json.load(f)
        mutar(d)
        bad = Path(TMP) / 'cat_val.json'
        bad.write_text(json.dumps(d), encoding='utf-8')
        with mock.patch.object(core, 'CATALOGO_FILE', bad):
            return core.load_catalogo()

    def _primer_cmd(self, d):
        return d['categorias'][1]['comandos'][0]

    def test_catalogo_real_es_valido(self):
        self.assertTrue(core.load_catalogo()['categorias'])

    def test_rechaza_accion_inexistente(self):
        with self.assertRaises(core.CatalogoError) as e:
            self._cargar(lambda d: self._primer_cmd(d).update(accion='no_existe'))
        self.assertIn('acción desconocida', str(e.exception))

    def test_rechaza_id_duplicado(self):
        def mutar(d):
            d['categorias'][1]['comandos'][1]['id'] = self._primer_cmd(d)['id']
        with self.assertRaises(core.CatalogoError) as e:
            self._cargar(mutar)
        self.assertIn('duplicado', str(e.exception))

    def test_rechaza_tipo_de_campo_que_nadie_pinta(self):
        with self.assertRaises(core.CatalogoError) as e:
            self._cargar(lambda d: self._primer_cmd(d).update(
                campos=[{'clave': 'x', 'tipo': 'slider'}]))
        self.assertIn('no saben pintar', str(e.exception))

    def test_rechaza_defecto_fuera_de_opciones(self):
        with self.assertRaises(core.CatalogoError) as e:
            self._cargar(lambda d: self._primer_cmd(d).update(
                campos=[{'clave': 'x', 'tipo': 'select', 'defecto': 'zzz',
                         'opciones': [{'valor': 'a'}]}]))
        self.assertIn('no está entre sus opciones', str(e.exception))

    def test_rechaza_select_obligatorio_con_opcion_vacia(self):
        with self.assertRaises(core.CatalogoError) as e:
            self._cargar(lambda d: self._primer_cmd(d).update(
                campos=[{'clave': 'x', 'tipo': 'select', 'defecto': 'a',
                         'opciones': [{'valor': 'a'}, {'valor': ''}]}]))
        self.assertIn('Falta el valor', str(e.exception))

    def test_select_con_opcion_vacia_pero_opcional_es_valido(self):
        self._cargar(lambda d: self._primer_cmd(d).update(
            campos=[{'clave': 'x', 'tipo': 'select', 'defecto': '', 'opcional': True,
                     'opciones': [{'valor': ''}, {'valor': 'a'}]}]))


class TestRedDeSeguridad(Base):
    """Que un botón que cambia el móvil no dependa de acordarse de escribir
    "confirmar" en el JSON."""

    def test_lectura_nunca_confirma(self):
        cat = core.load_catalogo()
        malos = [c['id'] for cat_ in cat['categorias'] for c in cat_.get('comandos', [])
                 if core.es_lectura(c) and core.necesita_confirmacion(c)]
        self.assertEqual(malos, [], f'botones de lectura pidiendo confirmación: {malos}')

    def test_accion_critica_confirma_aunque_el_json_lo_olvide(self):
        self.assertTrue(core.necesita_confirmacion({'id': 'x', 'accion': 'sideload'}))
        self.assertTrue(core.necesita_confirmacion({'id': 'x', 'accion': 'setprop'}))

    def test_se_puede_renunciar_a_proposito(self):
        self.assertFalse(core.necesita_confirmacion(
            {'id': 'x', 'accion': 'sideload', 'confirmar': False}))

    def test_integridad_todo_lo_critico_tiene_red(self):
        cat = core.load_catalogo()
        sin_red = []
        for c in cat['categorias']:
            for cmd in c.get('comandos', []):
                if cmd['accion'] in core.ACCIONES_CRITICAS and not core.necesita_confirmacion(cmd):
                    sin_red.append(cmd['id'])
        self.assertEqual(sin_red, [], f'acciones críticas sin confirmación: {sin_red}')

    def test_toda_accion_usada_esta_clasificada_o_es_mutante(self):
        # No exige clasificar todo: solo deja constancia de que lo no declarado
        # como lectura se trata como mutante, que es el lado seguro.
        cat = core.load_catalogo()
        for c in cat['categorias']:
            for cmd in c.get('comandos', []):
                if cmd['accion'] not in core.ACCIONES_LECTURA:
                    self.assertFalse(core.es_lectura(cmd))


class TestCompatibilidad(Base):
    """Avisar antes de pulsar, y nunca avisar en falso."""

    def _cmd(self, cid):
        for c in core.load_catalogo()['categorias']:
            for x in c.get('comandos', []):
                if x['id'] == cid:
                    return x
        raise AssertionError(cid)

    def test_sin_requisitos_siempre_compatible(self):
        self.assertEqual(core.compatibilidad({'id': 'x'}, {'sdk': 21}), (True, None))

    def test_sdk_insuficiente_se_marca_con_motivo(self):
        ok, motivo = core.compatibilidad(self._cmd('perf_game_mode'), {'sdk': 30})
        self.assertFalse(ok)
        self.assertIn('Android 12', motivo)

    def test_sdk_suficiente_es_compatible(self):
        self.assertTrue(core.compatibilidad(self._cmd('perf_game_mode'), {'sdk': 36})[0])

    def test_sin_dispositivo_no_marca_nada(self):
        # Un aviso en falso es peor que no avisar: el usuario deja de creerlos.
        for cid in ('perf_game_mode', 'role_holders', 'game_virtual'):
            self.assertTrue(core.compatibilidad(self._cmd(cid), {})[0], cid)
            self.assertTrue(core.compatibilidad(self._cmd(cid), None)[0], cid)

    def test_scrcpy_viejo_se_marca(self):
        with mock.patch.object(core, 'scrcpy_version', return_value=(2, 4)):
            ok, motivo = core.compatibilidad(self._cmd('game_pad'), {'sdk': 36})
        self.assertFalse(ok)
        self.assertIn('3.1', motivo)

    def test_scrcpy_desconocido_no_marca(self):
        with mock.patch.object(core, 'scrcpy_version', return_value=None):
            self.assertTrue(core.compatibilidad(self._cmd('game_pad'), {'sdk': 36})[0])


class TestCancelacion(Base):
    """Cancelar un comando largo, con sus tres carreras."""

    SPEC = {'id': 'lento', 'titulo': 'lento', 'accion': 'custom',
            'args': {'command': 'shell sleep 30'}}

    def _adb_lento(self):
        p = Path(TMP) / 'adb-lento'
        p.write_text('#!/bin/bash\n'
                     'case "$1" in devices) echo "List of devices attached";'
                     ' echo "SERIAL1  device"; exit 0;; esac\n'
                     'sleep 30\n')
        p.chmod(0o755)
        return p

    def test_cancelar_durante_devuelve_cancelado(self):
        with mock.patch.object(core, 'ADB_EXEC', str(self._adb_lento())):
            hechos = []
            w = core.start_command(self.SPEC, on_done=hechos.append)
            time.sleep(1.0)
            w.cancel()
            w.join(timeout=15)
        self.assertFalse(w.is_alive())
        self.assertEqual(len(hechos), 1, 'el contrato es UN solo callback terminal')
        self.assertTrue(hechos[0].get('cancelled'))
        self.assertFalse(hechos[0].get('success'))

    def test_cancelar_antes_de_arrancar(self):
        with mock.patch.object(core, 'ADB_EXEC', str(self._adb_lento())):
            hechos = []
            w = core.start_command(self.SPEC, on_done=hechos.append)
            w.cancel()
            w.join(timeout=15)
        self.assertFalse(w.is_alive())
        self.assertEqual(len(hechos), 1)
        self.assertTrue(hechos[0].get('cancelled'))

    def test_cancelar_despues_de_terminar_no_lanza(self):
        hechos = []
        w = core.start_command({'id': 'v', 'titulo': 'v', 'accion': 'version'},
                               on_done=hechos.append)
        w.join(timeout=15)
        w.cancel()          # no debe lanzar ni disparar un segundo callback
        self.assertEqual(len(hechos), 1)

    def test_no_deja_procesos_registrados(self):
        with mock.patch.object(core, 'ADB_EXEC', str(self._adb_lento())):
            w = core.start_command(self.SPEC, on_done=lambda r: None)
            time.sleep(0.8)
            w.cancel()
            w.join(timeout=15)
        self.assertEqual(core._procesos_en_curso, {})


if __name__ == '__main__':
    unittest.main()
