#!/usr/bin/env python3
"""Gekko ADB Studio - núcleo headless.

Prohibido importar `gi`/GTK aquí: lo usan la CLI, el selector bin/gekko-adb,
los frontends GTK 3/4 y los tests. Toda la ejecución de ADB/Scrcpy vive aquí.
"""
import configparser
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

APP_ID = 'com.gekko.adb'
APP_NAME = 'Gekko ADB Studio'
BASE_DIR = Path(os.environ.get('GEKKO_ADB_BASE', os.path.dirname(os.path.abspath(__file__))))

CATALOGO_FILE = BASE_DIR / 'adb_commands.json'
PRESETS_FILE = BASE_DIR / 'debloat_presets.json'

ADB_EXEC = os.environ.get('GEKKO_ADB_EXECUTABLE') or shutil.which('adb') or 'adb'
SCRCPY_EXEC = os.environ.get('GEKKO_SCRCPY_EXECUTABLE') or shutil.which('scrcpy') or 'scrcpy'

CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')))
STATE_HOME = Path(os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')))
CONFIG_DIR = CONFIG_HOME / 'gekko-adb'
CONFIG_FILE = CONFIG_DIR / 'config.ini'
LOG_DIR = STATE_HOME / 'gekko-adb' / 'logs'
LOG_FILE = LOG_DIR / 'gekko-adb.log'

_XDG_FALLBACKS = {
    'DOWNLOAD': ['Descargas', 'Downloads'],
    'MUSIC': ['Música', 'Music'],
    'PICTURES': ['Imágenes', 'Pictures'],
    'VIDEOS': ['Vídeos', 'Videos'],
}


def user_dir(name):
    """Resuelve XDG dirs del usuario (locale es_MX: ~/Descargas, ~/Música...)."""
    try:
        res = subprocess.run(['xdg-user-dir', name], capture_output=True, text=True, timeout=10)
        path = res.stdout.strip()
        if path and Path(path).is_absolute():
            return path
    except Exception:
        pass
    for cand in _XDG_FALLBACKS.get(name, []):
        p = Path.home() / cand
        if p.is_dir():
            return str(p)
    return str(Path.home())


def log_line(msg):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {msg}\n')
    except Exception:
        pass


def run(cmd_args, timeout=30):
    """Ejecuta un proceso y devuelve {'success', 'stdout', 'stderr'}."""
    try:
        res = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout)
        return {'success': res.returncode == 0,
                'stdout': res.stdout.strip(), 'stderr': res.stderr.strip()}
    except FileNotFoundError:
        return {'success': False, 'stdout': '',
                'stderr': f'No se encontró {cmd_args[0] if cmd_args else "comando"}'}
    except subprocess.TimeoutExpired:
        return {'success': False, 'stdout': '', 'stderr': f'Tiempo agotado ({timeout}s)'}
    except Exception as e:
        return {'success': False, 'stdout': '', 'stderr': str(e)}


def adb_base_args():
    """Prefija -s <serial> si hay más de un dispositivo conectado."""
    try:
        res = run([ADB_EXEC, 'devices'])
        lines = [ln for ln in res['stdout'].splitlines()[1:] if '\tdevice' in ln]
        if len(lines) > 1:
            return ['-s', lines[0].split('\t')[0]]
    except Exception:
        pass
    return []


def run_adb(cmd_args, timeout=30, multi=False):
    args = ([] if multi else adb_base_args()) + list(cmd_args)
    res = run([ADB_EXEC] + args, timeout=timeout)
    log_line(f'adb {" ".join(args)} -> {"OK" if res["success"] else "FAIL"}: '
             f'{res["stdout"][:200]} {res["stderr"][:200]}')
    return res


def run_scrcpy(scrcpy_args):
    """Lanza scrcpy desacoplado (Popen); no espera y no bloquea."""
    if not shutil.which(SCRCPY_EXEC):
        return {'success': False, 'stdout': '', 'stderr': 'scrcpy no está instalado'}
    try:
        subprocess.Popen([SCRCPY_EXEC] + scrcpy_args)
        return {'success': True, 'stdout': f'Scrcpy lanzado: {" ".join(scrcpy_args) or "(default)"}',
                'stderr': ''}
    except Exception as e:
        return {'success': False, 'stdout': '', 'stderr': str(e)}


# ----------------------------------------------------------------------
# Información del dispositivo (puerto de la web legacy, con parseo defensivo)

def get_devices():
    res = run_adb(['devices', '-l'], multi=True)
    devs = []
    for line in res['stdout'].splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            devs.append(parts[0])
    return devs


_BATTERY_HEALTH = {
    '1': 'Desconocido', '2': 'Bien', '3': 'Sobrecalentado', '4': 'Muerto',
    '5': 'Sobrevoltaje', '6': 'Falla inespecífica', '7': 'Frío',
}
_BATTERY_STATUS = {
    '1': 'Desconocido', '2': 'Cargando', '3': 'Descargando',
    '4': 'Sin carga', '5': 'Llena',
}


def _battery_clean(raw):
    if raw is None:
        return None
    val = str(raw).strip()
    if not val or val in ('-1', 'null'):
        return None
    return val


def _parse_battery_state(output):
    """Extrae {clave: valor} solo de la sección de estado de `dumpsys battery`.

    El match es estricto: corta en la primera sección con corchetes (p. ej.
    `[EventLogBuffer]`), así las líneas con timestamps y `Capacity level: -1`
    nunca contaminan `level`/`voltage`/`temperature`/`health`.
    """
    fields = {}
    in_state = False
    for ln in output.splitlines():
        stripped = ln.strip()
        if not in_state:
            if stripped.startswith('Current Battery Service state:'):
                in_state = True
            continue
        if stripped.startswith('['):
            break
        if ':' in ln:
            key, _, val = ln.partition(':')
            fields[key.strip()] = val.strip()
    return fields


def _parse_battery_properties(output):
    """Parsea `dumpsys batteryproperties` a los mismos campos de estado."""
    remap = {
        'battery_level': 'level', 'battery_scale': 'scale',
        'battery_status': 'status', 'battery_health': 'health',
        'battery_temperature': 'temperature', 'battery_voltage': 'voltage',
    }
    fields = {}
    for ln in output.splitlines():
        if ':' in ln:
            key, _, val = ln.partition(':')
            fields[key.strip()] = val.strip()
    return {dst: fields[src] for src, dst in remap.items() if fields.get(src)}


def _normalize_battery(fields):
    """Convierte campos crudos de batería en valores numéricos normalizados.

    `level` se normaliza con `scale` y se acota a 0-100; `-1`/`null` son
    desconocidos. Nunca devuelve un nivel negativo.
    """
    out = {}
    level = _battery_clean(fields.get('level'))
    if level is not None:
        try:
            pct = int(level)
            scale = _battery_clean(fields.get('scale'))
            if scale:
                s = int(scale)
                if s > 0:
                    pct = pct * 100 // s
            out['level'] = max(0, min(100, pct))
        except ValueError:
            pass
    temp = _battery_clean(fields.get('temperature'))
    if temp is not None:
        try:
            out['temp_tenths'] = int(float(temp))
        except ValueError:
            pass
    volt = _battery_clean(fields.get('voltage'))
    if volt is not None:
        try:
            out['voltage_mv'] = int(float(volt))
        except ValueError:
            pass
    status = _battery_clean(fields.get('status'))
    if status:
        out['status'] = status
    health = _battery_clean(fields.get('health'))
    if health:
        out['health'] = health
    return out


def _battery_sysfs():
    """Lee /sys/class/power_supply/battery/* (best-effort, no Samsung)."""
    fields = {}

    def cat(name):
        res = run_adb(['shell', 'cat', f'/sys/class/power_supply/battery/{name}'])
        return res['stdout'].strip()

    for src, dst in (('capacity', 'level'), ('temp', 'temperature')):
        val = cat(src)
        if val and val.isdigit():
            fields[dst] = val
    volt = cat('voltage_now')
    if volt and volt.isdigit():
        fields['voltage'] = str(int(volt) // 1000)  # µV → mV
    for src, dst, mapping in (
            ('status', 'status',
             {'Charging': '2', 'Discharging': '3', 'Full': '5', 'Not charging': '4'}),
            ('health', 'health',
             {'Good': '2', 'Overheat': '3', 'Dead': '4', 'Over voltage': '5', 'Cold': '7'})):
        val = cat(src)
        if val:
            fields[dst] = mapping.get(val, val)
    return _normalize_battery(fields)


def get_battery():
    """Batería con cadena de fallback: dumpsys battery → batteryproperties → sysfs."""
    dumpsys = _normalize_battery(
        _parse_battery_state(run_adb(['shell', 'dumpsys', 'battery'])['stdout']))
    if dumpsys:
        return dumpsys
    props = _normalize_battery(
        _parse_battery_properties(run_adb(['shell', 'dumpsys', 'batteryproperties'])['stdout']))
    if props:
        return props
    return _battery_sysfs()


def _wm_value(output, kind):
    """Valor efectivo de `wm {kind}` (Override > Forced > Physical)."""
    for prefix in ('Override', 'Forced', 'Physical'):
        marker = f'{prefix} {kind}:'
        for ln in output.splitlines():
            if ln.strip().startswith(marker):
                return ln.split(':', 1)[1].strip()
    return ''


def get_device_info():
    devices = get_devices()
    if not devices:
        return {'connected': False, 'serial': '', 'message': 'No hay dispositivo ADB conectado'}
    serial = devices[0]

    def gp(key):
        return run_adb(['shell', 'getprop', key])['stdout']

    def shell(cmd):
        return run_adb(['shell'] + cmd)['stdout']

    model = gp('ro.product.model')
    brand = gp('ro.product.brand')
    manufacturer = gp('ro.product.manufacturer')
    android = gp('ro.build.version.release')
    sdk = gp('ro.build.version.sdk')
    abi = gp('ro.product.cpu.abi')

    b = (brand or manufacturer or '').lower()
    if 'samsung' in b:
        marca = 'samsung'
    elif 'xiaomi' in b or 'redmi' in b or 'poco' in b:
        marca = 'xiaomi'
    else:
        marca = 'other'

    if marca == 'samsung':
        knox = gp('ro.boot.warranty_bit') or '0'
        secure = 'Knox 0x1 (Tripped)' if knox == '1' else 'Knox 0x0 (Valid)'
    elif marca == 'xiaomi':
        locked = gp('ro.boot.flash.locked')
        boot = {'1': 'Bloqueado', '0': 'Desbloqueado'}.get(locked, 'N/A')
        vb = gp('ro.boot.verifiedbootstate') or 'N/A'
        secure = f'Bootloader {boot} · Verified {vb}'
    else:
        se = shell(['getenforce']).strip() or 'N/A'
        secure = f'SELinux {se}'

    bat = get_battery()
    level = f"{bat['level']}%" if 'level' in bat else 'N/A'
    temp = f"{bat['temp_tenths'] / 10.0:g} °C" if 'temp_tenths' in bat else 'N/A'
    volt = (f"{bat['voltage_mv'] / 1000.0:.3f}".rstrip('0').rstrip('.') + ' V'
            if 'voltage_mv' in bat else 'N/A')
    health = _BATTERY_HEALTH.get(bat.get('health'), 'N/A')
    status = _BATTERY_STATUS.get(bat.get('status'), 'N/A')

    wm_size = _wm_value(shell(['wm', 'size']), 'size') or 'N/A'
    wm_density = _wm_value(shell(['wm', 'density']), 'density') or 'N/A'
    nav = shell(['settings', 'get', 'secure', 'navigation_mode']).strip()
    nav_mode = {'2': 'Gestos', '1': '3 Botones'}.get(nav, 'Predeterminado')
    home_role = shell(['cmd', 'role', 'get-role-holders', 'android.app.role.HOME']).strip()
    sms_role = shell(['cmd', 'role', 'get-role-holders', 'android.app.role.SMS']).strip()
    dialer_role = shell(['cmd', 'role', 'get-role-holders', 'android.app.role.DIALER']).strip()

    return {
        'connected': True,
        'serial': serial,
        'model': ' '.join(x for x in (brand.upper(), model) if x).strip(),
        'marca': marca,
        'android': f"Android {android} (API {sdk})",
        'abi': abi,
        'secure': secure,
        'battery': level,
        'temperature': temp,
        'voltage': volt,
        'health': health,
        'battery_status': status,
        'display': wm_size,
        'density': wm_density,
        'nav_mode': nav_mode,
        'home_role': home_role,
        'sms_role': sms_role,
        'dialer_role': dialer_role,
    }


def get_packages():
    res = run_adb(['shell', 'pm', 'list', 'packages', '-u'])
    return sorted(p.replace('package:', '') for p in res['stdout'].splitlines()
                  if p.startswith('package:'))


def get_processes():
    res = run_adb(['shell', 'ps', '-A'])
    return res['stdout'].splitlines()[:100]


def read_logcat(level='V', filtro=''):
    res = run_adb(['shell', 'logcat', '-d', f'*:{level}'])
    lines = res['stdout'].splitlines()
    if filtro:
        lines = [l for l in lines if filtro.lower() in l.lower()]
    return lines[-100:]


# ----------------------------------------------------------------------
# Acciones del catálogo

def _expand(path):
    return os.path.expanduser(path) if path else path


def act_devices():
    return run_adb(['devices', '-l'], multi=True)


def act_version():
    return run([ADB_EXEC, 'version'])


def act_start_server():
    if shutil.which('adb') is None:
        return {'success': False, 'stdout': '', 'stderr': 'android-tools no instalado'}
    return run([ADB_EXEC, 'start-server'])


def act_kill_server():
    return run([ADB_EXEC, 'kill-server'])


def act_host_features():
    return run_adb(['host-features'], multi=True)


def act_help():
    return run([ADB_EXEC, 'help'], timeout=15)


def act_tcpip(port):
    return run_adb(['tcpip', str(port)], multi=True)


def act_connect(ip):
    return run_adb(['connect', ip], multi=True)


def act_disconnect(ip):
    args = ['disconnect'] + ([ip] if ip else [])
    return run_adb(args, multi=True)


def act_usb():
    return run_adb(['usb'], multi=True)


def act_mdns_check():
    return run_adb(['mdns', 'check'], multi=True)


def act_mdns_services():
    return run_adb(['mdns', 'services'], multi=True)


def act_push(origen, destino):
    return run_adb(['push', _expand(origen), destino], timeout=3600)


def act_pull(origen, destino):
    target = _expand(destino)
    os.makedirs(target, exist_ok=True)
    return run_adb(['pull', origen, target], timeout=3600)


def act_sync(ruta):
    return run_adb(['sync', ruta], timeout=600)


def act_quick_pull(origen, destino, sub=''):
    target = user_dir(destino)
    if sub:
        target = os.path.join(target, sub)
    return act_pull(origen, target)


def act_install(apk, flags):
    apk = _expand(apk)
    if not os.path.exists(apk):
        return {'success': False, 'stdout': '', 'stderr': f'No existe: {apk}'}
    cmd = ['install'] + flags + [apk]
    return run_adb(cmd, timeout=300)


def act_install_multiple(apks, flags):
    apks = [_expand(a) for a in apks if a]
    if not apks:
        return {'success': False, 'stdout': '', 'stderr': 'No se seleccionaron APKs'}
    return run_adb(['install-multiple'] + flags + apks, timeout=600)


def act_uninstall(package, flags):
    return run_adb(['uninstall'] + flags + [package])


def act_restore(package):
    return run_adb(['shell', 'cmd', 'package', 'install-existing', package])


def act_extract_apk(package):
    path_res = run_adb(['shell', 'pm', 'path', package])
    apk_path = path_res['stdout'].replace('package:', '').splitlines()[0] if path_res['stdout'] else ''
    if not apk_path:
        return {'success': False, 'stdout': '', 'stderr': f'No se encontró APK para {package}'}
    target_dir = user_dir('DOWNLOAD')
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, f'{package}.apk')
    res = run_adb(['pull', apk_path, target], timeout=300)
    res['path'] = target
    return res


def act_sideload(ota):
    ota = _expand(ota)
    if not os.path.exists(ota):
        return {'success': False, 'stdout': '', 'stderr': f'No existe: {ota}'}
    return run_adb(['sideload', ota], timeout=1800)


def act_forward_list():
    return run_adb(['forward', '--list'], multi=True)


def act_forward_add(local, remoto):
    return run_adb(['forward', local, remoto], multi=True)


def act_forward_remove_all():
    return run_adb(['forward', '--remove-all'], multi=True)


def act_reverse_list():
    return run_adb(['reverse', '--list'], multi=True)


def act_reverse_add(remoto, local):
    return run_adb(['reverse', remoto, local], multi=True)


def act_reverse_remove_all():
    return run_adb(['reverse', '--remove-all'], multi=True)


def act_reboot(mode):
    if mode == 'soft':
        return run_adb(['shell', 'ctl.restart', 'zygote'])
    if mode == 'safemode':
        run_adb(['shell', 'setprop', 'persist.sys.safemode', '1'])
        return run_adb(['reboot'])
    if mode == 'normal':
        return run_adb(['reboot'])
    return run_adb(['reboot', mode])


def act_root():
    return run_adb(['root'], multi=True)


def act_unroot():
    return run_adb(['unroot'], multi=True)


def act_remount():
    return run_adb(['remount'], multi=True)


def act_bugreport():
    target_dir = user_dir('DOWNLOAD')
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = os.path.join(target_dir, f'bugreport_gekko_{stamp}.zip')
    res = run_adb(['bugreport', target], timeout=600)
    res['path'] = target
    return res


def act_custom(command):
    return run_adb(command.split())


def act_getprop(key):
    if key.strip():
        return run_adb(['shell', 'getprop', key])
    return run_adb(['shell', 'getprop'])


def act_setprop(key, value):
    return run_adb(['shell', 'setprop', key, value])


_PM_ACTIONS = {
    'disable': ['shell', 'pm', 'disable-user', '--user', '0'],
    'enable': ['shell', 'pm', 'enable'],
    'clear': ['shell', 'pm', 'clear'],
    'force-stop': ['shell', 'am', 'force-stop'],
    'uninstall': ['shell', 'pm', 'uninstall', '--user', '0'],
}


def act_pm_action(action, package):
    base = _PM_ACTIONS.get(action)
    if base is None:
        return {'success': False, 'stdout': '', 'stderr': f'Acción pm desconocida: {action}'}
    return run_adb(base + [package])


def act_debloat_preset(preset_spec):
    pkgs = preset_spec.get('paquetes', [])
    ok, fail = [], []
    for p in pkgs:
        res = act_pm_action('uninstall', p)
        (ok if res['success'] else fail).append(p)
    return {'success': len(fail) == 0,
            'stdout': f"Preset {preset_spec.get('id')}: {len(ok)} OK, "
                      f"{len(fail)} fallos: {' '.join(fail)}",
            'stderr': '' if not fail else 'Revisa la lista de fallos'}


def act_settings_put(space, key, value):
    return run_adb(['shell', 'settings', 'put', space, key, value])


def act_nav_mode(mode):
    return run_adb(['shell', 'settings', 'put', 'secure', 'navigation_mode', str(mode)])


def act_anim_scale(scale):
    s = str(scale)
    for k in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
        run_adb(['shell', 'settings', 'put', 'global', k, s])
    return {'success': True, 'stdout': f'Escala de animaciones fijada a {s}x', 'stderr': ''}


def act_density(dpi):
    return run_adb(['shell', 'wm', 'density', str(dpi)])


def act_density_reset():
    return run_adb(['shell', 'wm', 'density', 'reset'])


def act_wm_size(size):
    return run_adb(['shell', 'wm', 'size', size])


def act_wm_size_reset():
    return run_adb(['shell', 'wm', 'size', 'reset'])


def act_role_set(role, package):
    return run_adb(['shell', 'cmd', 'role', 'add-role-holder', role, package])


def act_role_list():
    roles = ['android.app.role.HOME', 'android.app.role.SMS',
             'android.app.role.DIALER', 'android.app.role.ASSISTANT', 'android.app.role.BROWSER']
    out = []
    for r in roles:
        res = run_adb(['shell', 'cmd', 'role', 'get-role-holders', r])
        out.append(f'{r}: {res["stdout"] or "(ninguno)"}')
    return {'success': True, 'stdout': '\n'.join(out), 'stderr': ''}


def act_input_key(key):
    return run_adb(['shell', 'input', 'keyevent', str(key)])


def act_input_text(text):
    return run_adb(['shell', 'input', 'text', text])


def act_input_tap(x, y):
    return run_adb(['shell', 'input', 'tap', str(x), str(y)])


def act_input_swipe(x1, y1, x2, y2, dur):
    return run_adb(['shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(dur)])


def act_dumpsys(servicio):
    return run_adb(['shell', 'dumpsys', servicio])


def act_top():
    return run_adb(['shell', 'top', '-n', '1'])


def act_logcat_read(level, filtro):
    lines = read_logcat(level, filtro)
    return {'success': True, 'stdout': '\n'.join(lines) or '(sin entradas)',
            'stderr': ''}


def act_logcat_clear():
    return run_adb(['logcat', '-c'])


def act_screenshot():
    target_dir = user_dir('PICTURES')
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, 'screenshot_gekko.png')
    run_adb(['shell', 'screencap', '-p', '/sdcard/screen.png'])
    res = run_adb(['pull', '/sdcard/screen.png', target])
    run_adb(['shell', 'rm', '/sdcard/screen.png'])
    res['path'] = target
    return res


def act_scrcpy(mode):
    cmd = []
    if mode == 'screenoff':
        cmd += ['-S', '--turn-screen-off']
    elif mode == 'fps120':
        cmd += ['--max-fps=120', '--video-bit-rate=16M']
    elif mode == 'record':
        rec_dir = user_dir('VIDEOS')
        os.makedirs(rec_dir, exist_ok=True)
        cmd += [f'--record={os.path.join(rec_dir, "scrcpy_record.mp4")}']
    elif mode == 'audio':
        cmd += ['--audio-codec=aac']
    elif mode == 'otg':
        cmd += ['--otg']
    return run_scrcpy(cmd)


def act_list_packages():
    pkgs = get_packages()
    return {'success': True, 'stdout': '\n'.join(pkgs) or '(sin paquetes)',
            'stderr': ''}


def act_processes():
    procs = get_processes()
    return {'success': True, 'stdout': '\n'.join(procs) or '(sin procesos)',
            'stderr': ''}


def act_device_info():
    info = get_device_info()
    if not info['connected']:
        return {'success': False, 'stdout': '', 'stderr': info['message']}
    lines = [f"{k}: {v}" for k, v in info.items() if k not in ('connected', 'serial')]
    return {'success': True, 'stdout': '\n'.join(lines), 'stderr': ''}


# ----------------------------------------------------------------------
# Despacho de acciones del catálogo
#
# Cada entrada del catálogo usa 'accion' + 'args' (fijos) + 'campos'
# (pedidos en el diálogo de la UI). El dispatch une los valores y llama
# a la función act_* correspondiente.

_ACTIONS = {
    'devices': lambda v, a: act_devices(),
    'version': lambda v, a: act_version(),
    'start_server': lambda v, a: act_start_server(),
    'kill_server': lambda v, a: act_kill_server(),
    'host_features': lambda v, a: act_host_features(),
    'help': lambda v, a: act_help(),
    'tcpip': lambda v, a: act_tcpip(v['port']),
    'connect': lambda v, a: act_connect(v['ip']),
    'disconnect': lambda v, a: act_disconnect(v.get('ip', '')),
    'usb': lambda v, a: act_usb(),
    'mdns_check': lambda v, a: act_mdns_check(),
    'mdns_services': lambda v, a: act_mdns_services(),
    'push': lambda v, a: act_push(v['origen'], v['destino']),
    'pull': lambda v, a: act_pull(v['origen'], v['destino']),
    'sync': lambda v, a: act_sync(v['ruta']),
    'quick_pull': lambda v, a: act_quick_pull(a['origen'], a['destino'], a.get('sub', '')),
    'install': lambda v, a: act_install(v['apk'], a.get('flags', [])),
    'install_multiple': lambda v, a: act_install_multiple(v['apks'], a.get('flags', [])),
    'uninstall': lambda v, a: act_uninstall(v['package'], a.get('flags', [])),
    'restore': lambda v, a: act_restore(v['package']),
    'extract_apk': lambda v, a: act_extract_apk(v['package']),
    'sideload': lambda v, a: act_sideload(v['ota']),
    'forward_list': lambda v, a: act_forward_list(),
    'forward_add': lambda v, a: act_forward_add(v['local'], v['remoto']),
    'forward_remove_all': lambda v, a: act_forward_remove_all(),
    'reverse_list': lambda v, a: act_reverse_list(),
    'reverse_add': lambda v, a: act_reverse_add(v['remoto'], v['local']),
    'reverse_remove_all': lambda v, a: act_reverse_remove_all(),
    'reboot': lambda v, a: act_reboot(a['mode']),
    'soft_reboot': lambda v, a: act_reboot('soft'),
    'root': lambda v, a: act_root(),
    'unroot': lambda v, a: act_unroot(),
    'remount': lambda v, a: act_remount(),
    'bugreport': lambda v, a: act_bugreport(),
    'custom': lambda v, a: act_custom(v['command']),
    'terminal': lambda v, a: act_custom(v['command']),
    'getprop': lambda v, a: act_getprop(v.get('key', '')),
    'setprop': lambda v, a: act_setprop(v['key'], v['value']),
    'pm_action': lambda v, a: act_pm_action(a['action'], v['package']),
    'debloat_preset': lambda v, a: act_debloat_preset(a['preset']),
    'settings_put': lambda v, a: act_settings_put(v['space'], v['key'], v['value']),
    'nav_mode': lambda v, a: act_nav_mode(a['mode']),
    'anim_scale': lambda v, a: act_anim_scale(a['scale']),
    'density': lambda v, a: act_density(v['dpi']),
    'density_reset': lambda v, a: act_density_reset(),
    'wm_size': lambda v, a: act_wm_size(v['size']),
    'wm_size_reset': lambda v, a: act_wm_size_reset(),
    'role_set': lambda v, a: act_role_set(a.get('role', v.get('role', 'android.app.role.HOME')),
                                          a.get('package', v.get('package', ''))),
    'role_list': lambda v, a: act_role_list(),
    'input_key': lambda v, a: act_input_key(a['key']),
    'input_text': lambda v, a: act_input_text(v['text']),
    'input_tap': lambda v, a: act_input_tap(v['x'], v['y']),
    'input_swipe': lambda v, a: act_input_swipe(v['x1'], v['y1'], v['x2'], v['y2'], v['dur']),
    'dumpsys': lambda v, a: act_dumpsys(a['servicio']),
    'top': lambda v, a: act_top(),
    'logcat_read': lambda v, a: act_logcat_read(v['level'], v.get('filter', '')),
    'logcat_clear': lambda v, a: act_logcat_clear(),
    'screenshot': lambda v, a: act_screenshot(),
    'scrcpy': lambda v, a: act_scrcpy(a['mode']),
    'list_packages': lambda v, a: act_list_packages(),
    'processes': lambda v, a: act_processes(),
    'device_info': lambda v, a: act_device_info(),
}


def build_valores(spec, valores_ui, flags_ui):
    """Une args fijos + valores de la UI en {clave: valor} para el dispatch."""
    campos = {c['clave']: c for c in spec.get('campos', [])}
    valores = {}
    for clave, val in (spec.get('args') or {}).items():
        valores[clave] = val
    for clave, val in (valores_ui or {}).items():
        if clave in campos or spec.get('accion') in ('custom', 'terminal'):
            valores[clave] = val
    if flags_ui:
        valores['flags'] = flags_ui
    return valores


def ejecutar(spec, valores_ui=None, flags_ui=None):
    """Ejecuta una especificación del catálogo. Devuelve dict resultado."""
    accion = spec.get('accion')
    if accion is None:
        return {'success': False, 'stdout': '', 'stderr': 'Sin acción definida'}
    handler = _ACTIONS.get(accion)
    if handler is None:
        return {'success': False, 'stdout': '', 'stderr': f'Acción desconocida: {accion}'}
    try:
        valores = build_valores(spec, valores_ui, flags_ui)
        return handler(valores, spec.get('args') or {})
    except KeyError as e:
        return {'success': False, 'stdout': '', 'stderr': f'Falta el valor: {e}'}
    except Exception as e:
        return {'success': False, 'stdout': '', 'stderr': str(e)}


class CommandWorker(threading.Thread):
    """Ejecuta una especificación del catálogo en segundo plano.

    Contrato: exactamente un callback terminal — `on_done(result)` con
    cualquier resultado (success True o False), o `on_error(err)` solo si
    el hilo abortó por excepción. Nunca llamar callbacks desde otro hilo;
    la UI debe aplicar el resultado con GLib.idle_add.
    """

    def __init__(self, spec, valores_ui=None, flags_ui=None, on_done=None, on_error=None):
        super().__init__(daemon=True)
        self._spec = spec
        self._valores = valores_ui or {}
        self._flags = flags_ui or []
        self._on_done = on_done
        self._on_error = on_error
        self._finished = False

    def run(self):
        try:
            result = ejecutar(self._spec, self._valores, self._flags)
        except Exception as e:
            if not self._finished:
                self._finished = True
                if self._on_error:
                    self._on_error(e)
            return
        if self._finished:
            return
        self._finished = True
        if self._on_done:
            self._on_done(result)


def start_command(spec, valores_ui=None, flags_ui=None, on_done=None, on_error=None):
    worker = CommandWorker(spec, valores_ui, flags_ui, on_done, on_error)
    worker.start()
    return worker


# ----------------------------------------------------------------------
# Catálogo, presets y configuración

def load_catalogo():
    with open(CATALOGO_FILE, encoding='utf-8') as f:
        return json.load(f)


def load_presets():
    with open(PRESETS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    return data.get('presets', [])


def preset_buttons():
    """Convierte cada preset en una especificación de catálogo ejecutable."""
    specs = []
    for p in load_presets():
        specs.append({
            'id': f'preset_{p["id"]}',
            'titulo': f'{p.get("icono", "🧹")} {p["titulo"]}',
            'desc': p.get('desc', ''),
            'accion': 'debloat_preset',
            'args': {'preset': p},
            'peligro': True,
            'confirmar': True,
        })
    return specs


def cargar_config():
    cfg = configparser.ConfigParser()
    cfg['General'] = {'theme': 'system', 'log_enabled': 'false'}
    try:
        cfg.read(CONFIG_FILE, encoding='utf-8')
    except Exception:
        pass
    return cfg


def guardar_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            cfg.write(f)
    except Exception:
        pass


def connectividad():
    """Estado rápido para el header de la UI."""
    info = get_device_info()
    return info


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--diagnostics':
        print(f'ADB: {ADB_EXEC} ({shutil.which("adb")})')
        print(f'Scrcpy: {SCRCPY_EXEC} ({shutil.which("scrcpy")})')
        print('Dispositivos:', get_devices() or '(ninguno)')
        sys.exit(0)
    print(json.dumps(connectividad(), indent=2, ensure_ascii=False))