#!/usr/bin/env python3
"""Gekko ADB Studio - núcleo headless.

Prohibido importar `gi`/GTK aquí: lo usan la CLI, el selector bin/gekko-adb,
los frontends GTK 3/4 y los tests. Toda la ejecución de ADB/Scrcpy vive aquí.

Contrato de resultados: toda acción devuelve un dict con 'success', 'stdout'
y 'stderr'; opcionalmente 'path' (solo cuando la operación tuvo éxito) e
'info' (datos estructurados del dashboard).
"""
import configparser
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

APP_ID = 'com.gekko.adb'
APP_NAME = 'Gekko ADB Studio'
APP_VERSION = '2.3.0'
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
LOG_MAX_BYTES = 1024 * 1024

_XDG_FALLBACKS = {
    'DOWNLOAD': ['Descargas', 'Downloads'],
    'MUSIC': ['Música', 'Music'],
    'PICTURES': ['Imágenes', 'Pictures'],
    'VIDEOS': ['Vídeos', 'Videos'],
}

# Subcomandos que hablan con el servidor adb del host y no necesitan -s.
_HOST_COMMANDS = {'devices', 'version', 'start-server', 'kill-server', 'host-features',
                  'connect', 'disconnect', 'pair', 'mdns', 'help', 'keygen', 'reconnect'}
_LONG_COMMANDS = {'pull', 'push', 'install', 'install-multiple', 'install-multi-package',
                  'sideload', 'bugreport', 'backup', 'restore', 'sync', 'wait-for-device'}

_PKG_RE = re.compile(r'^[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+$')
_ROLE_RE = re.compile(r'^[A-Za-z][\w.]*$')
_INT_RE = re.compile(r'^-?\d+$')


# ----------------------------------------------------------------------
# Utilidades

def user_dir(name):
    """Resuelve XDG dirs del usuario (locale es_MX: ~/Descargas, ~/Música...).

    xdg-user-dir devuelve $HOME cuando la clave no existe; en ese caso se
    usan los fallbacks y, si ninguno existe, se crea el primero.
    """
    home = Path.home()
    try:
        res = subprocess.run(['xdg-user-dir', name], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL,
                             timeout=10)
        path = res.stdout.strip().rstrip('/')
        if path and Path(path).is_absolute() and Path(path) != home:
            return path
    except Exception:
        pass
    cands = _XDG_FALLBACKS.get(name, [])
    for cand in cands:
        p = home / cand
        if p.is_dir():
            return str(p)
    if cands:
        return str(home / cands[0])
    return str(home)


_log_enabled = None


def logging_enabled():
    global _log_enabled
    if _log_enabled is None:
        try:
            _log_enabled = cargar_config().getboolean('General', 'log_enabled', fallback=False)
        except Exception:
            _log_enabled = False
    return _log_enabled


def set_logging(enabled):
    global _log_enabled
    _log_enabled = bool(enabled)


def log_line(msg, force=False):
    if not force and not logging_enabled():
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            os.replace(LOG_FILE, LOG_FILE.with_suffix('.log.1'))
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {msg}\n')
    except Exception:
        pass


def _fail(msg):
    return {'success': False, 'stdout': '', 'stderr': msg}


def _ok(msg):
    return {'success': True, 'stdout': msg, 'stderr': ''}


def _text(v):
    if v is None:
        return ''
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    return v


# Proceso en marcha de cada hilo, para poder cancelar desde la interfaz un
# comando largo (recompilar una app son minutos; bugreport y screenrecord
# tampoco son instantáneos). La clave es el ident del hilo que llamó a run():
# CommandWorker.cancel() busca ahí el proceso de SU hilo y lo termina, así que
# cancelar un comando nunca puede matar el de otro.
_procesos_en_curso = {}
_procesos_lock = threading.Lock()
_hilos_cancelados = set()


def _registrar_proceso(proc):
    with _procesos_lock:
        _procesos_en_curso[threading.get_ident()] = proc


def _olvidar_proceso():
    with _procesos_lock:
        _procesos_en_curso.pop(threading.get_ident(), None)


def cancelar_hilo(ident):
    """Termina el proceso que esté ejecutando ese hilo. True si había alguno.

    Marca además el hilo como cancelado para que el resultado salga como
    cancelado y no como un fallo real. Es seguro llamarla cuando el proceso ya
    terminó: entonces no hay nada que matar y devuelve False.
    """
    with _procesos_lock:
        _hilos_cancelados.add(ident)
        proc = _procesos_en_curso.get(ident)
    if proc is None:
        return False
    # Se mata el GRUPO entero, no solo el proceso: 'adb shell <algo largo>' deja
    # hijos, y matando únicamente al padre esos hijos siguen vivos con el pipe
    # abierto, así que communicate() se quedaría esperando para siempre.
    if not _matar_grupo(proc, signal.SIGTERM):
        return False
    try:
        proc.wait(timeout=2)
    except Exception:
        # No murió por las buenas: adb y scrcpy a veces ignoran SIGTERM.
        _matar_grupo(proc, signal.SIGKILL)
    return True


def _matar_grupo(proc, sig):
    """Envía la señal al grupo del proceso, con el propio proceso como respaldo."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill() if sig == signal.SIGKILL else proc.terminate()
            return True
        except Exception:
            return False


def hilo_cancelado(ident=None):
    with _procesos_lock:
        return (threading.get_ident() if ident is None else ident) in _hilos_cancelados


def limpiar_cancelado(ident):
    with _procesos_lock:
        _hilos_cancelados.discard(ident)


def run(cmd_args, timeout=30):
    """Ejecuta un proceso y devuelve {'success', 'stdout', 'stderr'}.

    Usa Popen en vez de subprocess.run para poder registrar el proceso y
    cancelarlo desde la interfaz. El valor de retorno, el tiempo de espera y el
    tratamiento de errores son exactamente los de antes.
    """
    proc = None
    try:
        # start_new_session pone al proceso en su propio grupo: sin eso, matar a
        # 'adb' dejaría vivos a sus hijos y communicate() esperaría el pipe abierto.
        proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                                errors='replace', start_new_session=True)
        _registrar_proceso(proc)
        # Carrera: si cancelaron entre que arrancó el hilo y este registro,
        # 'cancelar_hilo' no encontró proceso que matar. Se atiende aquí.
        if hilo_cancelado():
            _matar_grupo(proc, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return {'success': False, 'stdout': _text(out).strip(),
                    'stderr': (f'Tiempo agotado ({timeout}s)' +
                               ('\n' + _text(err).strip() if err else ''))}
        return {'success': proc.returncode == 0,
                'stdout': _text(out).strip(), 'stderr': _text(err).strip()}
    except FileNotFoundError:
        return _fail(f'No se encontró el ejecutable {cmd_args[0] if cmd_args else "comando"}')
    except Exception as e:
        return _fail(str(e))
    finally:
        if proc is not None:
            _olvidar_proceso()


def run_bytes(cmd_args, timeout=60):
    """Como run() pero devuelve stdout en bytes (para adb exec-out)."""
    try:
        res = subprocess.run(cmd_args, capture_output=True, stdin=subprocess.DEVNULL,
                             timeout=timeout)
        return {'success': res.returncode == 0, 'stdout': res.stdout,
                'stderr': res.stderr.decode('utf-8', 'replace').strip()}
    except FileNotFoundError:
        return {'success': False, 'stdout': b'',
                'stderr': f'No se encontró el ejecutable {cmd_args[0] if cmd_args else "comando"}'}
    except subprocess.TimeoutExpired:
        return {'success': False, 'stdout': b'', 'stderr': f'Tiempo agotado ({timeout}s)'}
    except Exception as e:
        return {'success': False, 'stdout': b'', 'stderr': str(e)}


# ----------------------------------------------------------------------
# Dispositivos y ejecución de adb

_transport_cache = {'t': 0.0, 'data': None}
_TRANSPORT_TTL = 1.5


def list_transports(fresh=False):
    """Devuelve ([(serial, estado)], resultado_adb) de `adb devices -l`.

    Estados posibles: device, unauthorized, offline, recovery, sideload,
    'no permissions', bootloader... Se cachea 1,5 s para no lanzar
    `adb devices` antes de cada comando de una ráfaga.
    """
    now = time.monotonic()
    if not fresh and _transport_cache['data'] and now - _transport_cache['t'] < _TRANSPORT_TTL:
        return _transport_cache['data']
    res = run([ADB_EXEC, 'devices', '-l'], timeout=20)
    devs = []
    for line in res['stdout'].splitlines():
        if not line.strip() or line.startswith('List of devices') or line.startswith('*'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        state = parts[1]
        if state == 'no' and len(parts) > 2 and parts[2].startswith('permissions'):
            state = 'no permissions'
        devs.append((parts[0], state))
    data = (devs, res)
    _transport_cache['t'] = now
    _transport_cache['data'] = data
    return data


def invalidate_transports():
    _transport_cache['data'] = None


def get_devices():
    """Seriales en estado 'device' (listos para usar)."""
    devs, _ = list_transports()
    return [s for s, st in devs if st == 'device']


def resolve_serial():
    """Serial a usar cuando hay más de un transporte (cualquier estado)."""
    devs, _ = list_transports()
    if len(devs) <= 1:
        return None
    for s, st in devs:
        if st == 'device':
            return s
    return devs[0][0]


def adb_base_args(serial=None):
    """Prefija -s <serial> si hay más de un transporte conectado."""
    try:
        serial = serial or resolve_serial()
    except Exception:
        serial = None
    return ['-s', serial] if serial else []


def _timeout_for(cmd_args, default):
    if cmd_args and cmd_args[0] in _LONG_COMMANDS:
        return max(default, 3600)
    return default


def run_adb(cmd_args, timeout=30, multi=False, serial=None, log=True, redact=False):
    """Ejecuta adb. multi=True solo para subcomandos de host (sin -s)."""
    cmd_args = [str(a) for a in cmd_args]
    args = ([] if multi else adb_base_args(serial)) + cmd_args
    res = run([ADB_EXEC] + args, timeout=timeout)
    if log:
        shown = ' '.join(args) if not redact else f'{cmd_args[0]} <redactado>'
        log_line(f'adb {shown} -> {"OK" if res["success"] else "FAIL"}: '
                 f'{res["stdout"][:200]} {res["stderr"][:200]}')
    if any(k in cmd_args for k in ('start-server', 'kill-server', 'connect', 'disconnect',
                                   'tcpip', 'usb', 'reboot', 'root', 'unroot', 'reconnect')):
        invalidate_transports()
    return res


def run_scrcpy(scrcpy_args):
    """Lanza scrcpy desacoplado; espera 1,5 s para detectar fallos inmediatos."""
    if not shutil.which(SCRCPY_EXEC):
        return _fail('scrcpy no está instalado')
    args = list(scrcpy_args)
    serial = resolve_serial()
    if serial:
        args = ['-s', serial] + args
    try:
        proc = subprocess.Popen([SCRCPY_EXEC] + args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        return _fail(str(e))
    try:
        proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        return _ok(f'Scrcpy lanzado: {" ".join(args) or "(default)"}')
    err = ''
    try:
        # 'with' cierra el pipe: sin esto Python avisa de un ResourceWarning por
        # cada lanzamiento fallido. Solo se cierra en esta rama, con el proceso
        # ya muerto: cerrarlo con scrcpy vivo le daría SIGPIPE al escribir.
        with proc.stderr:
            err = proc.stderr.read().decode('utf-8', 'replace').strip()
    except Exception:
        pass
    if proc.returncode == 0:
        return _ok(f'Scrcpy terminó: {" ".join(args) or "(default)"}')
    return _fail(err or f'scrcpy terminó con código {proc.returncode}')


def run_scrcpy_capture(scrcpy_args, timeout=60):
    """Ejecuta scrcpy y CAPTURA su salida (--list-encoders, --list-apps).

    run_scrcpy() lanza desacoplado y tira la salida: sirve para abrir una
    ventana, no para leer un listado. scrcpy escribe parte de los listados
    por stderr, así que en caso de éxito se juntan las dos salidas.
    """
    if not shutil.which(SCRCPY_EXEC):
        return _fail('scrcpy no está instalado')
    args = list(scrcpy_args)
    serial = resolve_serial()
    if serial:
        args = ['-s', serial] + args
    res = run([SCRCPY_EXEC] + args, timeout=timeout)
    log_line(f'scrcpy {" ".join(args)} -> {"OK" if res["success"] else "FAIL"}')
    if not res['success']:
        return {'success': False, 'stdout': res['stdout'],
                'stderr': res['stderr'] or f'scrcpy {" ".join(args)} falló'}
    # El banner y los avisos salen por stderr y el listado por stdout: en ese orden.
    salida = '\n'.join(t for t in (res['stderr'], res['stdout']) if t.strip())
    return _ok(salida or '(sin salida)')


# ----------------------------------------------------------------------
# Información del dispositivo

_BATTERY_HEALTH = {
    '1': 'Desconocido', '2': 'Bien', '3': 'Sobrecalentado', '4': 'Muerto',
    '5': 'Sobrevoltaje', '6': 'Falla inespecífica', '7': 'Frío',
}
_BATTERY_STATUS = {
    '1': 'Desconocido', '2': 'Cargando', '3': 'Descargando',
    '4': 'Sin carga', '5': 'Llena',
}
_NAV_MODES = {'0': '3 Botones', '1': '2 Botones', '2': 'Gestos'}
_STATE_MESSAGES = {
    'unauthorized': 'sin autorizar: acepta la depuración USB en el teléfono',
    'offline': 'offline: reconecta el cable o usa "Reconectar"',
    'no permissions': 'sin permisos USB: revisa las reglas udev (android-udev)',
    'recovery': 'en recovery',
    'sideload': 'en modo sideload',
    'bootloader': 'en bootloader/fastboot',
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


def _normalize_battery(fields):
    """Convierte campos crudos de batería en valores numéricos normalizados.

    `level` se normaliza con `scale` y se acota a 0-100; `-1`/`null` son
    desconocidos. Voltajes en µV y temperaturas en centésimas se sanean.
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
            t = int(float(temp))
            if abs(t) > 1500:
                t //= 10
            out['temp_tenths'] = t
        except ValueError:
            pass
    volt = _battery_clean(fields.get('voltage'))
    if volt is not None:
        try:
            v = int(float(volt))
            if v > 100000:
                v //= 1000
            out['voltage_mv'] = v
        except ValueError:
            pass
    status = _battery_clean(fields.get('status'))
    if status:
        out['status'] = status
    health = _battery_clean(fields.get('health'))
    if health:
        out['health'] = health
    return out


def _battery_sysfs(serial=None):
    """Lee /sys/class/power_supply/battery/* (best-effort, no Samsung)."""
    fields = {}

    def cat(name):
        res = run_adb(['shell', 'cat', f'/sys/class/power_supply/battery/{name}'],
                      serial=serial, log=False)
        return res['stdout'].strip() if res['success'] else ''

    for src, dst in (('capacity', 'level'), ('temp', 'temperature')):
        val = cat(src)
        if val and _INT_RE.match(val):
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


def get_battery(serial=None):
    """Batería con cadena de fallback: dumpsys battery → sysfs."""
    res = run_adb(['shell', 'dumpsys', 'battery'], serial=serial, log=False)
    dumpsys = _normalize_battery(_parse_battery_state(res['stdout'])) if res['success'] else {}
    if dumpsys:
        return dumpsys
    return _battery_sysfs(serial)


def _wm_value(output, kind):
    """Valor efectivo de `wm {kind}` (Override > Forced > Physical)."""
    for prefix in ('Override', 'Forced', 'Physical'):
        marker = f'{prefix} {kind}:'
        for ln in output.splitlines():
            if ln.strip().startswith(marker):
                return ln.split(':', 1)[1].strip()
    return ''


def _sdk_int(value):
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return 0


def role_holder(role, sdk, serial=None):
    """Titular de un rol. `cmd role get-role-holders` existe desde Android 14;
    antes se usan las claves de settings / resolve-activity."""
    if sdk >= 34 or sdk == 0:
        res = run_adb(['shell', 'cmd', 'role', 'get-role-holders', role], serial=serial, log=False)
        out = res['stdout'].strip()
        if res['success'] and out and 'Unknown command' not in out and 'Error' not in out:
            return out.replace(';', ', ')
        if sdk >= 34:
            return ''
    if role == 'android.app.role.HOME':
        res = run_adb(['shell', 'cmd', 'package', 'resolve-activity', '--brief',
                       '-c', 'android.intent.category.HOME', '-a', 'android.intent.action.MAIN'],
                      serial=serial, log=False)
        lines = [ln.strip() for ln in res['stdout'].splitlines() if '/' in ln]
        return lines[-1].split('/')[0] if lines else ''
    key = {'android.app.role.SMS': 'sms_default_application',
           'android.app.role.DIALER': 'dialer_default_application',
           'android.app.role.ASSISTANT': 'assistant'}.get(role)
    if key:
        res = run_adb(['shell', 'settings', 'get', 'secure', key], serial=serial, log=False)
        val = res['stdout'].strip()
        return '' if val in ('', 'null') else val.split('/')[0]
    return ''


def device_state_message(devs, adb_res):
    """Mensaje para el usuario cuando no hay un dispositivo en estado 'device'."""
    if not devs:
        if not adb_res['success'] and adb_res['stderr']:
            return f'ADB no disponible: {adb_res["stderr"]}'
        return 'No hay dispositivo ADB conectado'
    serial, state = devs[0]
    return f'Dispositivo {serial} {_STATE_MESSAGES.get(state, state)}'


def get_device_info():
    devs, adb_res = list_transports(fresh=True)
    ready = [s for s, st in devs if st == 'device']
    if not ready:
        return {'connected': False, 'serial': devs[0][0] if devs else '',
                'state': devs[0][1] if devs else '',
                'message': device_state_message(devs, adb_res)}
    serial = ready[0] if len(devs) > 1 else None
    display_serial = ready[0]

    def gp(key):
        return run_adb(['shell', 'getprop', key], serial=serial, log=False)['stdout'].strip()

    def shell(cmd):
        return run_adb(['shell'] + cmd, serial=serial, log=False)['stdout']

    first = run_adb(['shell', 'getprop', 'ro.build.version.sdk'], serial=serial, log=False)
    if not first['success'] or not first['stdout'].strip():
        return {'connected': False, 'serial': display_serial, 'state': 'error',
                'message': first['stderr'] or 'El dispositivo no responde a adb shell'}
    sdk_str = first['stdout'].strip()
    sdk = _sdk_int(sdk_str)

    model = gp('ro.product.model')
    brand = gp('ro.product.brand')
    manufacturer = gp('ro.product.manufacturer')
    android = gp('ro.build.version.release')
    abi = gp('ro.product.cpu.abi')

    b = (brand or manufacturer or '').lower()
    if 'samsung' in b:
        marca = 'samsung'
    elif 'xiaomi' in b or 'redmi' in b or 'poco' in b:
        marca = 'xiaomi'
    else:
        marca = 'other'

    if marca == 'samsung':
        knox = gp('ro.boot.warranty_bit') or gp('ro.warranty_bit')
        if knox == '':
            secure = 'Knox N/A'
        else:
            secure = 'Knox 0x1 (Tripped)' if knox == '1' else 'Knox 0x0 (Valid)'
    elif marca == 'xiaomi':
        locked = gp('ro.boot.flash.locked')
        boot = {'1': 'Bloqueado', '0': 'Desbloqueado'}.get(locked, 'N/A')
        vb = gp('ro.boot.verifiedbootstate') or 'N/A'
        secure = f'Bootloader {boot} · Verified {vb}'
    else:
        se = shell(['getenforce']).strip() or 'N/A'
        secure = f'SELinux {se}'

    bat = get_battery(serial)
    level = f"{bat['level']}%" if 'level' in bat else 'N/A'
    temp = f"{bat['temp_tenths'] / 10.0:g} °C" if 'temp_tenths' in bat else 'N/A'
    volt = (f"{bat['voltage_mv'] / 1000.0:.3f}".rstrip('0').rstrip('.') + ' V'
            if 'voltage_mv' in bat else 'N/A')
    health = _BATTERY_HEALTH.get(bat.get('health'), 'N/A')
    status = _BATTERY_STATUS.get(bat.get('status'), 'N/A')

    wm_size = _wm_value(shell(['wm', 'size']), 'size') or 'N/A'
    wm_density = _wm_value(shell(['wm', 'density']), 'density') or 'N/A'
    nav = shell(['settings', 'get', 'secure', 'navigation_mode']).strip()
    nav_mode = _NAV_MODES.get(nav, 'Desconocido' if nav in ('', 'null') else f'Modo {nav}')
    home_role = role_holder('android.app.role.HOME', sdk, serial)
    sms_role = role_holder('android.app.role.SMS', sdk, serial)
    dialer_role = role_holder('android.app.role.DIALER', sdk, serial)

    return {
        'connected': True,
        'serial': display_serial,
        'state': 'device',
        'model': ' '.join(x for x in (brand.upper(), model) if x).strip(),
        'marca': marca,
        'sdk': sdk,
        'android': f"Android {android} (API {sdk_str})",
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
        'transports': len(devs),
    }


def get_packages(filtro='-u'):
    """Lista de paquetes (vacía si adb falla). Ver act_list_packages para el resultado completo."""
    return _parse_packages(_pm_list(filtro)['stdout'])


def _pm_list(filtro='-u'):
    args = ['shell', 'pm', 'list', 'packages']
    if filtro:
        args += [filtro]
    return run_adb(args)


def _parse_packages(stdout):
    return sorted(p.replace('package:', '').strip() for p in stdout.splitlines()
                  if p.startswith('package:'))


def get_processes():
    res = run_adb(['shell', 'ps', '-A'])
    return res['stdout'].splitlines()


def read_logcat(level='V', filtro='', limit=300):
    res = run_adb(['shell', 'logcat', '-d', '-t', '2000', shlex.quote(f'*:{level}')])
    lines = res['stdout'].splitlines()
    if filtro:
        lines = [ln for ln in lines if filtro.lower() in ln.lower()]
    return lines[-limit:]


# ----------------------------------------------------------------------
# Validación de valores de la UI

def _expand(path):
    return os.path.expanduser(path.strip()) if path else ''


def _need(value, nombre):
    if value is None or not str(value).strip():
        raise ValueError(f'Falta el valor: {nombre}')
    return str(value).strip()


def _int(value, nombre):
    v = _need(value, nombre)
    if not _INT_RE.match(v):
        raise ValueError(f'{nombre} debe ser un número entero (recibido: {v!r})')
    return v


def _package(value):
    v = _need(value, 'paquete')
    if not _PKG_RE.match(v):
        raise ValueError(f'Nombre de paquete no válido: {v!r}')
    return v


def _opcion(value, nombre, validos):
    """Valor OBLIGATORIO de lista cerrada (los _sc_* de Gaming aceptan vacío)."""
    v = _need(value, nombre)
    if v not in validos:
        raise ValueError(f'{nombre} no válido: {v!r} (valores: {", ".join(validos)})')
    return v


def _q(value):
    """Cita un valor para el shell del teléfono (adb shell reinterpreta los argumentos)."""
    return shlex.quote(str(value))


def _pm_result(res):
    """pm/cmd imprimen 'Success'/'Failure [...]'; el exit code no siempre lo refleja."""
    out = (res['stdout'] + '\n' + res['stderr'])
    if 'Failure' in out or out.strip().startswith('Error') or 'Exception' in out:
        res['success'] = False
        if not res['stderr']:
            res['stderr'] = res['stdout']
    elif 'Success' in out:
        res['success'] = True
    return res


# ----------------------------------------------------------------------
# Acciones del catálogo: servidor y conexión

def act_devices():
    devs, res = list_transports(fresh=True)
    if res['success'] and not devs:
        res['stdout'] = res['stdout'] or 'List of devices attached'
        res['stdout'] += '\n(ningún dispositivo)'
    return res


def act_version():
    return run([ADB_EXEC, 'version'])


def act_start_server():
    if not shutil.which(ADB_EXEC):
        return _fail(f'No se encontró adb ({ADB_EXEC}); instala android-tools')
    res = run([ADB_EXEC, 'start-server'])
    invalidate_transports()
    return res


def act_kill_server():
    res = run([ADB_EXEC, 'kill-server'])
    invalidate_transports()
    if res['success']:
        res['stdout'] = res['stdout'] or 'Servidor ADB detenido (el siguiente refresco lo relanza)'
    return res


def act_host_features():
    return run_adb(['host-features'], multi=True)


def act_help():
    return run([ADB_EXEC, 'help'], timeout=15)


def act_tcpip(port):
    port = _int(port, 'puerto')
    res = run_adb(['tcpip', port])
    if res['success'] and 'restarting' not in res['stdout'].lower():
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout']
    return res


def act_connect(ip):
    ip = _need(ip, 'IP')
    res = run_adb(['connect', ip], multi=True, timeout=20)
    out = res['stdout'].lower()
    if 'connected to' in out and not out.startswith(('failed', 'unable', 'cannot')):
        res['success'] = True
    else:
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout'] or f'No se pudo conectar a {ip}'
    invalidate_transports()
    return res


def act_disconnect(ip):
    args = ['disconnect'] + ([ip.strip()] if ip and ip.strip() else [])
    return run_adb(args, multi=True)


def act_pair(ip, code):
    ip = _need(ip, 'IP:puerto de emparejamiento')
    code = _int(code, 'código')
    res = run_adb(['pair', ip, code], multi=True, timeout=60)
    if 'Successfully paired' not in res['stdout']:
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout']
    return res


def act_reconnect(target=''):
    args = ['reconnect'] + ([target] if target in ('offline', 'device') else [])
    return run_adb(args, multi=(target != 'device'), timeout=20)


def act_usb():
    return run_adb(['usb'])


def act_mdns_check():
    res = run_adb(['mdns', 'check'], multi=True)
    if 'not supported' in (res['stdout'] + res['stderr']).lower():
        res['success'] = False
        res['stderr'] = 'Este adb no soporta mDNS (el android-tools de Arch se compila sin él); usa platform-tools de Google.'
    return res


def act_mdns_services():
    res = run_adb(['mdns', 'services'], multi=True, timeout=20)
    if 'not supported' in (res['stdout'] + res['stderr']).lower():
        res['success'] = False
        res['stderr'] = 'Este adb no soporta mDNS (el android-tools de Arch se compila sin él); usa platform-tools de Google.'
    return res


def _wifi_ip(serial=None):
    """IP del teléfono en la Wi-Fi: (ip, '') o (None, error de adb)."""
    res = run_adb(['shell', 'ip', '-f', 'inet', 'addr', 'show', 'wlan0'], serial=serial)
    m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', res['stdout'])
    if m:
        return m.group(1), ''
    res2 = run_adb(['shell', 'ip', 'route', 'get', '1.1.1.1'], serial=serial)
    m = re.search(r'src (\d+\.\d+\.\d+\.\d+)', res2['stdout'])
    if m:
        return m.group(1), ''
    return None, res['stderr'] or res2['stderr']


def act_device_ip():
    ip, err = _wifi_ip()
    if not ip:
        return _fail('No se encontró IP Wi-Fi (¿está conectado a una red?)\n' + err)
    return _ok(f'IP Wi-Fi del teléfono: {ip}  (usa {ip}:5555 tras "Activar puerto TCP/IP")')


# «Pasar a Wi-Fi» hace en un clic lo que antes eran tres botones (IP Wi-Fi,
# Activar puerto TCP/IP y Conectar por IP) sin copiar la IP a mano. adbd tarda
# un instante en reiniciarse en modo TCP, así que el connect se reintenta: el
# primero suele llegar antes de que el puerto escuche y devuelve «refused».
_WIFI_INTENTOS = 6
_WIFI_PAUSA = 1.0


def _es_inalambrico(serial):
    """'192.168.1.9:5555' (TCP/IP) o 'adb-XXXX._adb-tls-connect._tcp' (mDNS)."""
    return ':' in serial or serial.startswith('adb-')


def act_wifi_auto(port='5555'):
    port = _int(port, 'puerto')
    if not 1 <= int(port) <= 65535:
        raise ValueError(f'Puerto fuera de rango: {port} (1-65535)')
    listos = get_devices()
    if not listos:
        return _fail('No hay ningún móvil listo: conéctalo con el cable USB, acepta la '
                     'depuración USB en el teléfono y vuelve a pulsar.')
    usb = [s for s in listos if not _es_inalambrico(s)]
    if not usb:
        return _ok(f'Ya estás conectado por Wi-Fi ({", ".join(listos)}): no hace falta el cable.')
    serial = usb[0]
    ip, err = _wifi_ip(serial)
    if not ip:
        return _fail('El móvil no tiene IP en la Wi-Fi: conéctalo a la misma red que el PC '
                     'y vuelve a pulsar.\n' + err)
    res = run_adb(['tcpip', port], serial=serial)
    if not res['success'] or 'restarting' not in res['stdout'].lower():
        return _fail(res['stderr'] or res['stdout'] or f'adb tcpip {port} falló')
    destino = f'{ip}:{port}'
    for intento in range(_WIFI_INTENTOS):
        if intento:
            time.sleep(_WIFI_PAUSA)
        res = act_connect(destino)
        if res['success']:
            return _ok(f'Conectado por Wi-Fi a {destino}. Ya puedes quitar el cable: el '
                       'espejo y el gaming siguen por Wi-Fi.\nAl reiniciar el móvil se pierde '
                       'el modo TCP/IP: vuelve a pulsar con el cable puesto.')
    return _fail(f'El móvil abrió el puerto {port} pero no responde en {destino}: comprueba '
                 'que el PC y el móvil están en la misma Wi-Fi y que el router no aísla a '
                 'los clientes.\n' + res['stderr'])


def act_get_state():
    out = []
    ok = True
    for name, args in (('Estado', ['get-state']), ('Serial', ['get-serialno']),
                       ('Ruta USB', ['get-devpath'])):
        res = run_adb(args, timeout=15)
        ok = ok and res['success']
        out.append(f'{name}: {res["stdout"] or res["stderr"]}')
    return {'success': ok, 'stdout': '\n'.join(out), 'stderr': ''}


def act_wait_for_device():
    res = run_adb(['wait-for-device'], timeout=120)
    if res['success']:
        res['stdout'] = res['stdout'] or 'Dispositivo disponible'
    invalidate_transports()
    return res


# ----------------------------------------------------------------------
# Archivos y transferencia

def _merge_move(src_dir, dst_dir):
    """Mueve el contenido de src_dir dentro de dst_dir fusionando carpetas."""
    os.makedirs(dst_dir, exist_ok=True)
    for entry in os.listdir(src_dir):
        s = os.path.join(src_dir, entry)
        d = os.path.join(dst_dir, entry)
        if os.path.isdir(s) and os.path.isdir(d):
            _merge_move(s, d)
            os.rmdir(s)
        else:
            if os.path.exists(d):
                os.remove(d) if not os.path.isdir(d) else shutil.rmtree(d)
            shutil.move(s, d)


def act_push(origen, destino, sync=False):
    origen = _expand(_need(origen, 'archivo local'))
    destino = _need(destino, 'ruta en el celular')
    if not os.path.exists(origen):
        return _fail(f'No existe: {origen}')
    args = ['push'] + (['--sync'] if sync else []) + [origen, destino]
    return run_adb(args, timeout=3600)


def act_pull(origen, destino):
    origen = _need(origen, 'ruta en el celular')
    target = _expand(_need(destino, 'carpeta destino en PC'))
    os.makedirs(target, exist_ok=True)
    return run_adb(['pull', origen, target], timeout=3600)


def act_pull_merge(origen, destino):
    """pull de una carpeta remota dejando su CONTENIDO directamente en destino.

    `adb pull` anida la carpeta remota dentro de un destino existente; se
    baja a un directorio temporal dentro del destino y se fusiona.
    """
    origen = _need(origen, 'ruta en el celular').rstrip('/') or '/'
    target = _expand(_need(destino, 'carpeta destino en PC'))
    os.makedirs(target, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    staging = os.path.join(target, f'.gekko_pull_{stamp}')
    res = run_adb(['pull', origen, staging], timeout=3600)
    if not res['success']:
        shutil.rmtree(staging, ignore_errors=True)
        return res
    try:
        if os.path.isdir(staging):
            _merge_move(staging, target)
            os.rmdir(staging)
        elif os.path.exists(staging):
            os.replace(staging, os.path.join(target, os.path.basename(origen)))
    except OSError as e:
        return _fail(f'Copiado pero no se pudo fusionar en {target}: {e}')
    res['path'] = target
    return res


def act_sync_push(origen, destino):
    return act_push(origen, destino, sync=True)


def act_quick_pull(origen, destino, sub=''):
    target = user_dir(destino)
    if sub:
        target = os.path.join(target, sub)
    return act_pull_merge(origen, target)


# ----------------------------------------------------------------------
# Instalación

def _apk_list(value):
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = str(value or '').splitlines()
    return [_expand(a) for a in items if a and a.strip()]


def act_install(apk, flags):
    apk = _expand(_need(apk, 'archivo .apk'))
    if not os.path.exists(apk):
        return _fail(f'No existe: {apk}')
    res = run_adb(['install'] + list(flags or []) + [apk], timeout=300)
    return _pm_result(res)


def act_install_multiple(apks, flags):
    apks = _apk_list(apks)
    if not apks:
        return _fail('No se seleccionaron APKs')
    missing = [a for a in apks if not os.path.exists(a)]
    if missing:
        return _fail('No existe: ' + ', '.join(missing))
    res = run_adb(['install-multiple'] + list(flags or []) + apks, timeout=600)
    return _pm_result(res)


def act_install_multi_package(apks, flags):
    apks = _apk_list(apks)
    if not apks:
        return _fail('No se seleccionaron APKs')
    missing = [a for a in apks if not os.path.exists(a)]
    if missing:
        return _fail('No existe: ' + ', '.join(missing))
    res = run_adb(['install-multi-package'] + list(flags or []) + apks, timeout=900)
    return _pm_result(res)


def act_uninstall(package, flags):
    package = _package(package)
    if '-k' in (flags or []):
        # adb rechaza 'uninstall -k'; la forma soportada es vía cmd package.
        res = run_adb(['shell', 'cmd', 'package', 'uninstall', '-k', package])
    else:
        res = run_adb(['uninstall', package])
    return _pm_result(res)


def act_restore(package):
    package = _package(package)
    return _pm_result(run_adb(['shell', 'cmd', 'package', 'install-existing', package]))


def act_extract_apk(package):
    package = _package(package)
    path_res = run_adb(['shell', 'pm', 'path', package])
    paths = [ln.replace('package:', '').strip() for ln in path_res['stdout'].splitlines()
             if ln.startswith('package:')]
    if not paths:
        return _fail(f'No se encontró APK para {package}\n{path_res["stderr"]}'.strip())
    target_dir = user_dir('DOWNLOAD')
    os.makedirs(target_dir, exist_ok=True)
    if len(paths) == 1:
        target = os.path.join(target_dir, f'{package}.apk')
        res = run_adb(['pull', paths[0], target], timeout=300)
        if res['success']:
            res['path'] = target
            res['stdout'] = f'APK extraído: {target}'
        return res
    out_dir = os.path.join(target_dir, package)
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    for p in paths:
        res = run_adb(['pull', p, os.path.join(out_dir, os.path.basename(p))], timeout=300)
        if not res['success']:
            errors.append(f'{p}: {res["stderr"] or res["stdout"]}')
    if errors:
        return _fail('Fallaron: ' + '; '.join(errors))
    return {'success': True, 'path': out_dir, 'stderr': '',
            'stdout': (f'{len(paths)} APKs (base + splits) en {out_dir}. '
                       f'Reinstala con "Instalar múltiples APKs" seleccionándolos todos.')}


def act_sideload(ota):
    ota = _expand(_need(ota, 'paquete OTA'))
    if not os.path.exists(ota):
        return _fail(f'No existe: {ota}')
    return run_adb(['sideload', ota], timeout=1800)


# ----------------------------------------------------------------------
# Puertos

def act_forward_list():
    return run_adb(['forward', '--list'], multi=True)


def act_forward_add(local, remoto):
    return run_adb(['forward', _need(local, 'local'), _need(remoto, 'remoto')])


def act_forward_remove_all():
    return run_adb(['forward', '--remove-all'])


def act_reverse_list():
    return run_adb(['reverse', '--list'])


def act_reverse_add(remoto, local):
    return run_adb(['reverse', _need(remoto, 'remoto'), _need(local, 'local')])


def act_reverse_remove_all():
    return run_adb(['reverse', '--remove-all'])


# ----------------------------------------------------------------------
# Boot y sistema

def _setprop_checked(key, value):
    res = run_adb(['shell', 'setprop', key, value])
    out = (res['stdout'] + res['stderr']).lower()
    if 'failed' in out or 'denied' in out or 'not found' in out:
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout']
    return res


def act_reboot(mode):
    if mode == 'soft':
        res = _setprop_checked('ctl.restart', 'zygote')
        if not res['success']:
            res['stderr'] = ('No se pudo reiniciar zygote (requiere adb root / build userdebug): '
                             + res['stderr']).strip()
        else:
            res['stdout'] = res['stdout'] or 'Zygote reiniciado (reinicio suave)'
        return res
    if mode == 'safemode':
        res = _setprop_checked('persist.sys.safemode', '1')
        if not res['success']:
            res['stderr'] = ('No se pudo activar el modo seguro (requiere root); no se reinició: '
                             + res['stderr']).strip()
            return res
        return run_adb(['reboot'])
    if mode == 'normal':
        return run_adb(['reboot'])
    if mode not in ('bootloader', 'recovery', 'sideload', 'sideload-auto-reboot',
                    'download', 'fastboot', 'edl'):
        return _fail(f'Modo de reinicio desconocido: {mode}')
    return run_adb(['reboot', mode])


def _root_result(res, expect):
    out = (res['stdout'] + ' ' + res['stderr']).lower()
    if 'restarting' in out or 'already' in out or ('not running as root' in out and expect == 'unroot'):
        res['success'] = True
        return res
    res['success'] = False
    res['stderr'] = res['stderr'] or res['stdout'] or 'adbd no aceptó el cambio'
    if 'production' in out:
        res['stderr'] += ' (build de producción: solo builds userdebug/eng permiten adb root)'
    return res


def act_root():
    return _root_result(run_adb(['root']), 'root')


def act_unroot():
    return _root_result(run_adb(['unroot']), 'unroot')


def act_remount():
    return run_adb(['remount'])


def act_bugreport():
    target_dir = user_dir('DOWNLOAD')
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = os.path.join(target_dir, f'bugreport_gekko_{stamp}.zip')
    res = run_adb(['bugreport', target], timeout=600)
    if res['success'] and os.path.exists(target):
        res['path'] = target
    return res


# ----------------------------------------------------------------------
# Shell y consola

def parse_custom_command(command):
    """'adb shell ls "a b"' -> ['shell', 'ls', 'a b']; quita el prefijo adb."""
    try:
        tokens = shlex.split(_need(command, 'comando'))
    except ValueError as e:
        raise ValueError(f'Comillas sin cerrar en el comando: {e}')
    if tokens and tokens[0] == 'adb':
        tokens = tokens[1:]
    if not tokens:
        raise ValueError('Falta el valor: comando')
    return tokens


def act_custom(command):
    tokens = parse_custom_command(command)
    if tokens[0] == 'shell' and len(tokens) == 1:
        return _fail('La consola no es interactiva: escribe "shell <comando>", p. ej. shell getprop ro.product.model')
    if tokens[0] == 'logcat' and '-d' not in tokens and '-t' not in tokens and '-c' not in tokens and '-g' not in tokens:
        tokens = tokens[:1] + ['-d'] + tokens[1:]
    multi = tokens[0] in _HOST_COMMANDS
    return run_adb(tokens, timeout=_timeout_for(tokens, 120), multi=multi)


def act_getprop(key):
    key = (key or '').strip()
    if key:
        return run_adb(['shell', 'getprop', _q(key)])
    return run_adb(['shell', 'getprop'])


def act_setprop(key, value):
    return _setprop_checked(_q(_need(key, 'clave')), _q(_need(value, 'valor')))


# ----------------------------------------------------------------------
# Gestor de paquetes

_PM_ACTIONS = {
    'disable': ['shell', 'pm', 'disable-user', '--user', '0'],
    'enable': ['shell', 'pm', 'enable', '--user', '0'],
    'clear': ['shell', 'pm', 'clear'],
    'force-stop': ['shell', 'am', 'force-stop'],
    'uninstall': ['shell', 'pm', 'uninstall', '--user', '0'],
    'grant': ['shell', 'pm', 'grant'],
    'revoke': ['shell', 'pm', 'revoke'],
}


def act_pm_action(action, package, extra=None, serial=None):
    base = _PM_ACTIONS.get(action)
    if base is None:
        return _fail(f'Acción pm desconocida: {action}')
    package = _package(package)
    args = base + [package]
    if action in ('grant', 'revoke'):
        perm = _need(extra, 'permiso')
        if not _ROLE_RE.match(perm):
            return _fail(f'Permiso no válido: {perm!r}')
        args.append(perm)
    return _pm_result(run_adb(args, serial=serial))


def act_list_packages(filtro='-u'):
    flag = {'todas': '-u', '-u': '-u', '-3': '-3', '-s': '-s', '-d': '-d', '-e': '-e', '': ''}.get(filtro, '-u')
    res = _pm_list(flag)
    if not res['success']:
        return res
    pkgs = _parse_packages(res['stdout'])
    res['stdout'] = '\n'.join(pkgs) or '(sin paquetes)'
    res['packages'] = pkgs
    return res


_APPOPS_MODES = ('allow', 'ignore', 'deny', 'default')
_APPOPS_OP_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_:.]{0,63}$')


def _appops_op(value):
    v = _need(value, 'operación de appops')
    if not _APPOPS_OP_RE.match(v):
        raise ValueError(f'Operación de appops no válida: {v!r} '
                         '(ejemplos: SYSTEM_ALERT_WINDOW, RUN_IN_BACKGROUND)')
    return v


def act_appops_get(package, op=''):
    """cmd appops get <paquete> [<op>]: permisos finos, más allá de pm grant."""
    args = ['shell', 'cmd', 'appops', 'get', _package(package)]
    if op is not None and str(op).strip():
        args.append(_appops_op(op))
    res = run_adb(args, timeout=60)
    if res['success'] and not res['stdout'].strip():
        res['stdout'] = '(sin operaciones registradas para ese paquete)'
    return res


def act_appops_set(package, op, mode):
    """cmd appops set <paquete> <op> <allow|ignore|deny|default>."""
    res = _pm_result(run_adb(['shell', 'cmd', 'appops', 'set', _package(package),
                              _appops_op(op), _opcion(mode, 'modo', _APPOPS_MODES)]))
    if res['success'] and not res['stdout'].strip():
        res['stdout'] = f'appops set {package} {op} {mode}: OK'
    return res


def _preset_packages(preset_spec):
    pkgs = preset_spec.get('paquetes')
    if not isinstance(pkgs, list) or not pkgs or not all(isinstance(p, str) and _PKG_RE.match(p) for p in pkgs):
        raise ValueError(f'Preset {preset_spec.get("id")}: "paquetes" debe ser una lista de nombres de paquete')
    return list(dict.fromkeys(pkgs))


def act_debloat_preset(preset_spec):
    pkgs = _preset_packages(preset_spec)
    serial = resolve_serial()
    ok, skipped, fail = [], [], []
    for p in pkgs:
        res = run_adb(_PM_ACTIONS['uninstall'] + [p], serial=serial)
        out = res['stdout'] + ' ' + res['stderr']
        if 'Success' in out:
            ok.append(p)
        elif 'not installed' in out or 'Unknown package' in out or 'DELETE_FAILED_INTERNAL_ERROR' in out:
            skipped.append(p)
        else:
            fail.append(f'{p} ({out.strip()[:80]})')
    lines = [f"Preset {preset_spec.get('id')}: {len(ok)} desinstalados, {len(skipped)} ya no estaban, {len(fail)} fallos."]
    if skipped:
        lines.append('Omitidos: ' + ' '.join(skipped))
    if fail:
        lines.append('Fallos: ' + ' '.join(fail))
    lines.append('Para deshacer: botón "Restaurar" del preset (cmd package install-existing).')
    return {'success': not fail, 'stdout': '\n'.join(lines),
            'stderr': '' if not fail else 'Revisa la lista de fallos'}


def act_restore_preset(preset_spec):
    pkgs = _preset_packages(preset_spec)
    serial = resolve_serial()
    ok, fail = [], []
    for p in pkgs:
        res = _pm_result(run_adb(['shell', 'cmd', 'package', 'install-existing', p], serial=serial))
        (ok if res['success'] else fail).append(p)
    return {'success': not fail,
            'stdout': f"Preset {preset_spec.get('id')}: {len(ok)} restaurados" +
                      (f", {len(fail)} no se pudieron restaurar: {' '.join(fail)}" if fail else ''),
            'stderr': ''}


# ----------------------------------------------------------------------
# Ajustes y pantalla

_SETTINGS_SPACES = ('secure', 'global', 'system')


def _space(space):
    space = _need(space, 'espacio')
    if space not in _SETTINGS_SPACES:
        raise ValueError(f'Espacio no válido: {space} (secure, global o system)')
    return space


def act_settings_put(space, key, value):
    return run_adb(['shell', 'settings', 'put', _space(space), _q(_need(key, 'clave')),
                    _q(_need(value, 'valor'))])


def act_settings_get(space, key):
    return run_adb(['shell', 'settings', 'get', _space(space), _q(_need(key, 'clave'))])


def act_settings_list(space):
    return run_adb(['shell', 'settings', 'list', _space(space)])


def act_settings_delete(space, key):
    return run_adb(['shell', 'settings', 'delete', _space(space), _q(_need(key, 'clave'))])


_NAV_OVERLAYS = {'0': 'threebutton', '1': 'twobutton', '2': 'gestural'}


def act_nav_mode(mode):
    """Cambia el modo de navegación activando el overlay RRO correspondiente.

    `settings put secure navigation_mode` no basta: SystemUI lo sobrescribe
    a partir del overlay activo. En Samsung y Xiaomi se ajusta además la
    clave propia del fabricante.
    """
    mode = str(mode)
    overlay = _NAV_OVERLAYS.get(mode)
    if overlay is None:
        return _fail(f'Modo de navegación desconocido: {mode}')
    serial = resolve_serial()
    brand = run_adb(['shell', 'getprop', 'ro.product.manufacturer'], serial=serial, log=False)['stdout'].lower()
    steps = []
    res = run_adb(['shell', 'cmd', 'overlay', 'enable-exclusive', '--category',
                   f'com.android.internal.systemui.navbar.{overlay}'], serial=serial)
    steps.append(('overlay', res))
    if 'samsung' in brand:
        steps.append(('samsung', run_adb(['shell', 'settings', 'put', 'global',
                                          'navigation_bar_gesture_while_hidden',
                                          '1' if mode == '2' else '0'], serial=serial)))
    elif 'xiaomi' in brand:
        steps.append(('xiaomi', run_adb(['shell', 'settings', 'put', 'global', 'force_fsg_nav_bar',
                                         '1' if mode == '2' else '0'], serial=serial)))
    time.sleep(1.0)
    check = run_adb(['shell', 'settings', 'get', 'secure', 'navigation_mode'], serial=serial, log=False)
    got = check['stdout'].strip()
    lines = [f'{name}: {"OK" if r["success"] else "ERROR"} {r["stdout"] or r["stderr"]}'.strip()
             for name, r in steps]
    lines.append(f'navigation_mode ahora: {got} ({_NAV_MODES.get(got, "?")})')
    success = any(r['success'] for _, r in steps) and (got == mode or got == '')
    if got and got != mode:
        lines.append('El sistema no aplicó el cambio: en esta ROM puede requerir hacerlo desde Ajustes.')
    return {'success': success, 'stdout': '\n'.join(lines),
            'stderr': '' if success else 'No se pudo cambiar el modo de navegación'}


def act_anim_scale(scale):
    s = str(scale)
    if not re.match(r'^\d+(\.\d+)?$', s):
        return _fail(f'Escala no válida: {s}')
    errors = []
    for k in ('window_animation_scale', 'transition_animation_scale', 'animator_duration_scale'):
        res = run_adb(['shell', 'settings', 'put', 'global', k, s])
        if not res['success']:
            errors.append(f'{k}: {res["stderr"] or res["stdout"]}')
    if errors:
        return _fail('No se pudo fijar la escala de animaciones:\n' + '\n'.join(errors))
    return _ok(f'Escala de animaciones fijada a {s}x')


def act_density(dpi):
    return run_adb(['shell', 'wm', 'density', _int(dpi, 'DPI')])


def act_density_reset():
    return run_adb(['shell', 'wm', 'density', 'reset'])


def act_wm_size(size):
    size = _need(size, 'tamaño')
    if not re.match(r'^\d+x\d+$', size):
        return _fail(f'Tamaño no válido: {size!r} (formato ANCHOxALTO, p. ej. 1080x2400)')
    return run_adb(['shell', 'wm', 'size', size])


def act_wm_size_reset():
    return run_adb(['shell', 'wm', 'size', 'reset'])


def act_brightness_get():
    """cmd display get-brightness --unit percentage (sin --unit devuelve 0.0-1.0)."""
    res = run_adb(['shell', 'cmd', 'display', 'get-brightness', '--unit', 'percentage'])
    valor = res['stdout'].strip()
    if res['success'] and valor:
        res['stdout'] = f'Brillo actual: {valor} %'
    return res


def act_brightness_set(nivel):
    nivel = _sc_uint(nivel, 'Brillo')
    if int(nivel) > 100:
        return _fail(f'El brillo va de 0 a 100 % (recibido: {nivel})')
    res = run_adb(['shell', 'cmd', 'display', 'set-brightness', nivel, '--unit', 'percentage'])
    if res['success'] and not res['stdout'].strip():
        res['stdout'] = f'Brillo fijado al {nivel} %'
    return res


_ROTATIONS = {'auto': None, '0': '0', '90': '1', '180': '2', '270': '3'}


def act_rotation(mode):
    mode = str(mode)
    if mode not in _ROTATIONS:
        return _fail(f'Rotación desconocida: {mode}')
    if mode == 'auto':
        return run_adb(['shell', 'settings', 'put', 'system', 'accelerometer_rotation', '1'])
    r1 = run_adb(['shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0'])
    r2 = run_adb(['shell', 'settings', 'put', 'system', 'user_rotation', _ROTATIONS[mode]])
    ok = r1['success'] and r2['success']
    return {'success': ok, 'stdout': f'Rotación fijada a {mode}°' if ok else '',
            'stderr': '' if ok else (r1['stderr'] + r2['stderr'])}


# ----------------------------------------------------------------------
# Roles

_KNOWN_ROLES = ('android.app.role.HOME', 'android.app.role.SMS', 'android.app.role.DIALER',
                'android.app.role.ASSISTANT', 'android.app.role.BROWSER')


def act_role_set(role, package):
    role = _need(role, 'rol')
    if not _ROLE_RE.match(role):
        return _fail(f'Rol no válido: {role!r}')
    package = _package(package)
    res = run_adb(['shell', 'cmd', 'role', 'add-role-holder', role, package], timeout=60)
    out = res['stdout'] + res['stderr']
    if 'Error' in out or 'Exception' in out or 'Unknown command' in out:
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout']
    if res['success'] and not res['stdout']:
        res['stdout'] = f'{package} asignado como {role.rsplit(".", 1)[-1]}'
    return res


def act_role_list():
    serial = resolve_serial()
    res = run_adb(['shell', 'getprop', 'ro.build.version.sdk'], serial=serial, log=False)
    if not res['success']:
        return res
    sdk = _sdk_int(res['stdout'])
    out = []
    for r in _KNOWN_ROLES:
        out.append(f'{r}: {role_holder(r, sdk, serial) or "(ninguno)"}')
    if sdk and sdk < 34:
        out.append('(Android < 14: sin "cmd role get-role-holders"; valores derivados de settings/resolve-activity)')
    return _ok('\n'.join(out))


# ----------------------------------------------------------------------
# Input

def act_input_key(key):
    return run_adb(['shell', 'input', 'keyevent', _int(key, 'keycode')])


def act_input_text(text):
    text = _need(text, 'texto')
    return run_adb(['shell', 'input', 'text', _q(text.replace(' ', '%s'))], redact=True)


def act_input_tap(x, y):
    return run_adb(['shell', 'input', 'tap', _int(x, 'X'), _int(y, 'Y')])


def act_input_swipe(x1, y1, x2, y2, dur):
    return run_adb(['shell', 'input', 'swipe', _int(x1, 'X inicial'), _int(y1, 'Y inicial'),
                    _int(x2, 'X final'), _int(y2, 'Y final'), _int(dur, 'duración')])


# ----------------------------------------------------------------------
# Diagnóstico

def act_dumpsys(servicio, extra=None):
    servicio = _need(servicio, 'servicio')
    if not re.match(r'^[\w./-]+$', servicio):
        return _fail(f'Servicio no válido: {servicio!r}')
    args = ['shell', 'dumpsys', servicio]
    if extra:
        args += [_q(e) for e in (extra if isinstance(extra, list) else [extra])]
    return run_adb(args, timeout=60)


def act_dumpsys_package(package):
    return run_adb(['shell', 'dumpsys', 'package', _package(package)], timeout=60)


def act_dumpsys_app(servicio, package):
    """dumpsys <servicio> <paquete>: gfxinfo y similares piden el paquete aparte.

    act_dumpsys() recibe el 'extra' fijo del catálogo; aquí el paquete lo
    escribe el usuario, así que pasa por _package().
    """
    servicio = _need(servicio, 'servicio')
    if not re.match(r'^[\w./-]+$', servicio):
        return _fail(f'Servicio no válido: {servicio!r}')
    return run_adb(['shell', 'dumpsys', servicio, _package(package)], timeout=60)


def act_battery_cmd(cmd):
    cmds = {'unplug': ['unplug'], 'reset': ['reset'], 'level20': ['set', 'level', '20'],
            'level100': ['set', 'level', '100']}
    if cmd not in cmds:
        return _fail(f'Comando de batería desconocido: {cmd}')
    return run_adb(['shell', 'dumpsys', 'battery'] + cmds[cmd])


def act_top():
    res = run_adb(['shell', 'top', '-b', '-n', '1', '-m', '40'])
    res['stdout'] = res['stdout'].replace('\r', '')
    return res


def act_logcat_read(level, filtro):
    level = (level or 'V').strip().upper()[:1] or 'V'
    if level not in 'VDIWEFS':
        return _fail(f'Nivel de logcat no válido: {level}')
    res = run_adb(['shell', 'logcat', '-d', '-t', '2000', shlex.quote(f'*:{level}')], timeout=60)
    if not res['success']:
        return res
    lines = res['stdout'].splitlines()
    if filtro:
        lines = [ln for ln in lines if filtro.lower() in ln.lower()]
    total = len(lines)
    lines = lines[-300:]
    head = f'({total} líneas, se muestran las últimas {len(lines)})' if total > len(lines) else ''
    res['stdout'] = '\n'.join(([head] if head else []) + lines) or '(sin entradas)'
    return res


def act_logcat_clear():
    return run_adb(['logcat', '-c'])


def act_processes():
    res = run_adb(['shell', 'ps', '-A'])
    if res['success'] and not res['stdout']:
        res['stdout'] = '(sin procesos)'
    return res


def act_screenshot():
    target_dir = user_dir('PICTURES')
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = os.path.join(target_dir, f'screenshot_gekko_{stamp}.png')
    raw = run_bytes([ADB_EXEC] + adb_base_args() + ['exec-out', 'screencap', '-p'], timeout=60)
    if raw['success'] and raw['stdout'].startswith(b'\x89PNG'):
        with open(target, 'wb') as f:
            f.write(raw['stdout'])
        return {'success': True, 'stdout': f'Captura guardada: {target}', 'stderr': '', 'path': target}
    remote = '/sdcard/gekko_screen.png'
    shot = run_adb(['shell', 'screencap', '-p', remote])
    if not shot['success']:
        return shot
    res = run_adb(['pull', remote, target])
    run_adb(['shell', 'rm', remote], log=False)
    if res['success']:
        res['path'] = target
        res['stdout'] = f'Captura guardada: {target}'
    return res


def act_screenrecord(seconds):
    secs = int(_int(seconds, 'segundos'))
    if not 1 <= secs <= 180:
        return _fail('La duración debe estar entre 1 y 180 segundos')
    target_dir = user_dir('VIDEOS')
    os.makedirs(target_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = os.path.join(target_dir, f'screenrecord_gekko_{stamp}.mp4')
    remote = '/sdcard/gekko_screenrecord.mp4'
    rec = run_adb(['shell', 'screenrecord', '--time-limit', str(secs), remote], timeout=secs + 60)
    if not rec['success']:
        return rec
    res = run_adb(['pull', remote, target], timeout=600)
    run_adb(['shell', 'rm', remote], log=False)
    if res['success']:
        res['path'] = target
        res['stdout'] = f'Vídeo guardado: {target}'
    return res


def act_storage():
    return run_adb(['shell', 'df', '-h', '/data', '/sdcard'])


def act_ime_list():
    res = run_adb(['shell', 'ime', 'list', '-s'])
    if res['success'] and not res['stdout']:
        res['stdout'] = '(sin teclados)'
    return res


def act_ime_set(ime_id):
    ime_id = _need(ime_id, 'id del teclado')
    if not re.match(r'^[\w.]+/[\w.$]+$', ime_id):
        return _fail(f'Id de teclado no válido: {ime_id!r} (formato paquete/.Servicio)')
    return run_adb(['shell', 'ime', 'set', ime_id])


# ----------------------------------------------------------------------
# Apps, overlays, servicios

def act_app_launch(package):
    package = _package(package)
    res = run_adb(['shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'])
    if 'No activities found' in res['stdout'] or 'monkey aborted' in res['stdout']:
        res['success'] = False
        res['stderr'] = res['stderr'] or res['stdout']
    elif res['success']:
        res['stdout'] = f'{package} lanzado'
    return res


def act_app_info(package):
    package = _package(package)
    return run_adb(['shell', 'am', 'start', '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS',
                    '-d', f'package:{package}'])


def act_open_url(url):
    url = _need(url, 'URL')
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', url):
        url = 'https://' + url
    return run_adb(['shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', _q(url)])


def act_am_start(intent):
    intent = _need(intent, 'acción')
    if not re.match(r'^[\w.]+$', intent):
        return _fail(f'Acción no válida: {intent!r}')
    return run_adb(['shell', 'am', 'start', '-a', intent])


def act_overlay_list():
    return run_adb(['shell', 'cmd', 'overlay', 'list'], timeout=60)


def act_overlay_toggle(package, enable):
    package = _package(package)
    return run_adb(['shell', 'cmd', 'overlay', 'enable' if enable else 'disable', package])


_SVC = {
    'wifi_on': ['svc', 'wifi', 'enable'], 'wifi_off': ['svc', 'wifi', 'disable'],
    'data_on': ['svc', 'data', 'enable'], 'data_off': ['svc', 'data', 'disable'],
    'bt_on': ['svc', 'bluetooth', 'enable'], 'bt_off': ['svc', 'bluetooth', 'disable'],
    'stayon': ['svc', 'power', 'stayon', 'true'], 'stayoff': ['svc', 'power', 'stayon', 'false'],
}


def act_svc(what):
    args = _SVC.get(what)
    if args is None:
        return _fail(f'Servicio desconocido: {what}')
    res = run_adb(['shell'] + args)
    if res['success'] and not res['stdout']:
        res['stdout'] = f'{" ".join(args)}: OK'
    return res


_NETPOLICY_READS = {
    'status': ['get', 'restrict-background'],
    'blacklist': ['list', 'restrict-background-blacklist'],
    'whitelist': ['list', 'restrict-background-whitelist'],
    'wifi': ['list', 'wifi-networks'],
}


def act_netpolicy(what):
    """Lecturas de 'cmd netpolicy' (datos en segundo plano y redes medidas)."""
    args = _NETPOLICY_READS.get(what)
    if args is None:
        return _fail(f'Consulta de netpolicy desconocida: {what}')
    res = run_adb(['shell', 'cmd', 'netpolicy'] + args, timeout=60)
    if res['success'] and not res['stdout'].strip():
        res['stdout'] = '(lista vacía)'
    return res


def act_netpolicy_restrict(estado):
    """cmd netpolicy set restrict-background <true|false> (Ahorro de datos global)."""
    estado = _opcion(estado, 'estado', ('true', 'false'))
    res = run_adb(['shell', 'cmd', 'netpolicy', 'set', 'restrict-background', estado])
    if res['success'] and not res['stdout'].strip():
        res['stdout'] = f'Ahorro de datos (restrict-background): {estado}'
    return res


def act_statusbar(what):
    if what not in ('expand-notifications', 'expand-settings', 'collapse'):
        return _fail(f'Acción de barra de estado desconocida: {what}')
    res = run_adb(['shell', 'cmd', 'statusbar', what])
    if res['success'] and not res['stdout']:
        res['stdout'] = f'statusbar {what}: OK'
    return res


def act_scrcpy(mode, v=None):
    cmd = []
    if mode == 'screenoff':
        cmd += ['--turn-screen-off']
    elif mode == 'fps120':
        cmd += ['--max-fps=120', '--video-bit-rate=16M']
    elif mode == 'record':
        rec_dir = user_dir('VIDEOS')
        os.makedirs(rec_dir, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        cmd += [f'--record={os.path.join(rec_dir, f"scrcpy_{stamp}.mp4")}']
    elif mode == 'audio':
        cmd += ['--audio-codec=aac']
    elif mode == 'otg':
        cmd += ['--otg']
    elif mode != 'standard':
        return _fail(f'Modo scrcpy desconocido: {mode}')
    return run_scrcpy(cmd + _sc_salida(v or {}))


# ----------------------------------------------------------------------
# Gaming: jugar en la PC con scrcpy (teclado, ratón y mando reales)
#
# Los valores llegan de la interfaz y acaban en un argv (nunca en un shell),
# pero igual se validan: una bandera mal formada hace que scrcpy aborte y el
# usuario solo vería "scrcpy terminó con código 1".

_SC_GAME_MODES = ('kbm', 'gamepad', 'virtual', 'otg', 'lowlat')
_SC_CODECS = ('h264', 'h265', 'av1', 'vp8', 'vp9')
_SC_HID_MODES = ('disabled', 'sdk', 'uhid', 'aoa')
_SC_PAD_MODES = ('disabled', 'uhid', 'aoa')
_SC_BITRATE_RE = re.compile(r'^\d{1,12}[KM]?$', re.IGNORECASE)
_SC_ENCODER_RE = re.compile(r'^[A-Za-z0-9][\w.-]*$')
_SC_DISPLAY_RE = re.compile(r'^(\d{1,5}x\d{1,5})?(/\d{1,4})?$')
# El primer carácter no puede ser un guion: '?--otg' llegaría como un solo
# argumento (no hay inyección), pero es basura que scrcpy rechazaría a su modo.
_SC_APPNAME_RE = re.compile(r'^[\w][\w .-]{0,99}$')


def _sc_str(valor):
    return str(valor).strip() if valor is not None else ''


def _sc_choice(valor, nombre, validos):
    """Valida un valor de lista cerrada; vacío significa "no pases la bandera"."""
    v = _sc_str(valor)
    if v and v not in validos:
        raise ValueError(f'{nombre} no válido: {v!r} (valores: {", ".join(validos)})')
    return v


_SC_FALSOS = ('', '0', 'no', 'false', 'off')


def _sc_bool(valor):
    """Interruptor de la interfaz: vacío, '0', 'no', 'false' y 'off' = desactivado.

    Un `if valor:` a secas daba por activado el '0' del select, así que
    "No" encendía la bandera.
    """
    return _sc_str(valor).lower() not in _SC_FALSOS


def _sc_uint(valor, nombre, maximo=None):
    """Entero >= 0: un negativo aquí acabaría como '-m -5' y scrcpy abortaría.

    Con `maximo` se acota también por arriba, igual que hacen la tasa de refresco
    (1-480 Hz) y el brillo (0-100): un valor absurdo no tiene por qué llegar al móvil.
    """
    v = _int(valor, nombre)
    if v.startswith('-'):
        raise ValueError(f'{nombre} no puede ser negativo (recibido: {v})')
    if maximo is not None and int(v) > maximo:
        raise ValueError(f'{nombre} no puede pasar de {maximo} (recibido: {v})')
    return v


def _sc_bitrate(valor):
    v = _sc_str(valor)
    if not _SC_BITRATE_RE.match(v):
        raise ValueError(f'Bitrate no válido: {v!r} (ejemplos: 9M, 4M, 9000000)')
    return v.upper()


def _sc_encoder(valor):
    v = _sc_str(valor)
    if not _SC_ENCODER_RE.match(v):
        raise ValueError(f'Codificador no válido: {v!r} (ejemplo: c2.android.avc.encoder; '
                         'míralos con "Listar codificadores")')
    return v


def _sc_new_display(valor):
    """--new-display[=[<ancho>x<alto>][/<dpi>]]; vacío = tamaño y dpi de la pantalla real."""
    v = _sc_str(valor)
    if not v:
        return '--new-display'
    if v == '/' or not _SC_DISPLAY_RE.match(v):
        raise ValueError(f'Pantalla virtual no válida: {v!r} '
                         '(ejemplos: 1920x1080, 1920x1080/420, /240)')
    return f'--new-display={v}'


def _sc_start_app(valor):
    """--start-app=[+][?]nombre: paquete exacto, o '?' para buscar por nombre."""
    v = _sc_str(valor)
    resto = v[1:] if v.startswith('+') else v
    buscar = resto.startswith('?')
    if buscar:
        resto = resto[1:]
    if buscar:
        if not _SC_APPNAME_RE.match(resto):
            raise ValueError(f'Nombre de app no válido: {v!r}')
    elif not _PKG_RE.match(resto):
        raise ValueError(f'Paquete no válido: {v!r} (usa el prefijo "?" para buscar por nombre, '
                         'por ejemplo ?genshin)')
    return f'--start-app={v}'


# Ventana y sonido: las dos preguntas comunes a todo botón que abre vídeo. El
# valor vacío es el comportamiento por defecto de scrcpy y no genera bandera.
_SC_VENTANAS = {'': [], 'fullscreen': ['--fullscreen'], 'borderless': ['--window-borderless']}
# 'output' (el defecto) manda el sonido al PC y calla el móvil; para que suene
# en los dos hay que capturar 'playback' y duplicarlo, y eso pide Android 13.
_SC_SONIDOS = {'': [], 'pc_movil': ['--audio-source=playback', '--audio-dup'],
               'movil': ['--no-audio']}


def _sc_salida(v):
    ventana = _sc_choice(v.get('ventana'), 'Modo de ventana', tuple(k for k in _SC_VENTANAS if k))
    sonido = _sc_choice(v.get('sonido'), 'Sonido', tuple(k for k in _SC_SONIDOS if k))
    return _SC_VENTANAS[ventana] + _SC_SONIDOS[sonido]


def scrcpy_game_args(v):
    """Construye la lista de banderas de scrcpy para los botones de Gaming.

    Un campo vacío no genera bandera: nunca sale un '--video-encoder=' colgando.
    """
    modo = _sc_str(v.get('mode')) or 'kbm'
    if modo not in _SC_GAME_MODES:
        raise ValueError(f'Modo de gaming desconocido: {modo!r}')
    args = []
    if modo == 'otg':
        # Sin vídeo ni adb: solo se inyectan teclado/ratón/mando por USB.
        args.append('--otg')
    else:
        if _sc_str(v.get('max_size')):
            args += ['-m', _sc_uint(v.get('max_size'), 'Resolución máxima')]
        if _sc_str(v.get('bitrate')):
            args += ['-b', _sc_bitrate(v.get('bitrate'))]
        codec = _sc_choice(v.get('codec'), 'Códec de vídeo', _SC_CODECS)
        if codec:
            args.append(f'--video-codec={codec}')
        if _sc_str(v.get('encoder')):
            args.append(f'--video-encoder={_sc_encoder(v.get("encoder"))}')
        if _sc_str(v.get('max_fps')):
            args.append(f'--max-fps={_sc_uint(v.get("max_fps"), "FPS máximos")}')
        if _sc_str(v.get('video_buffer')):
            args.append(f'--video-buffer={_sc_uint(v.get("video_buffer"), "Búfer de vídeo")}')
        if modo == 'virtual':
            args.append(_sc_new_display(v.get('new_display')))
        if _sc_str(v.get('package')):
            args.append(_sc_start_app(v.get('package')))
        if v.get('no_audio'):
            args.append('--no-audio')
        args += _sc_salida(v)
        if _sc_bool(v.get('screen_off')):
            args.append('--turn-screen-off')
    teclado = _sc_choice(v.get('keyboard'), 'Teclado', _SC_HID_MODES)
    if teclado:
        args.append(f'--keyboard={teclado}')
    raton = _sc_choice(v.get('mouse'), 'Ratón', _SC_HID_MODES)
    if raton:
        args.append(f'--mouse={raton}')
    mando = _sc_choice(v.get('gamepad'), 'Mando', _SC_PAD_MODES)
    if mando:
        args.append(f'--gamepad={mando}')
    return args


def act_scrcpy_game(v):
    return run_scrcpy(scrcpy_game_args(v))


_SC_LISTS = {'encoders': '--list-encoders', 'apps': '--list-apps'}


def act_scrcpy_list(what):
    """Listados de scrcpy que hay que LEER, no lanzar en una ventana aparte."""
    flag = _SC_LISTS.get(what)
    if flag is None:
        return _fail(f'Listado de scrcpy desconocido: {what}')
    return run_scrcpy_capture([flag], timeout=90)


# ----------------------------------------------------------------------
# Volumen del sonido del móvil EN EL PC
#
# scrcpy no tiene bandera de volumen: reproduce el audio como un programa más
# del escritorio. Así que el volumen se cambia donde vive ese sonido, en
# PipeWire/PulseAudio, con pactl: se buscan los flujos cuyo proceso es scrcpy y
# se les fija el volumen. El volumen del móvil no se toca.

PACTL_EXEC = os.environ.get('GEKKO_PACTL_EXECUTABLE') or shutil.which('pactl') or 'pactl'
_VOL_MAX = 150
_VOL_PASO = 10


def _es_flujo_scrcpy(flujo):
    # Los clientes que van por pipewire-pulse traen el binario, pero los nativos
    # de PipeWire (scrcpy 5 sale por SDL3) pueden llegar solo con application.name
    # o node.name: scrcpy fija su nombre con la pista SDL_APP_NAME.
    props = flujo.get('properties') or {}
    if os.path.basename(str(props.get('application.process.binary', ''))) == 'scrcpy':
        return True
    return any('scrcpy' in str(props.get(k, '')).lower() for k in ('application.name', 'node.name'))


def _volumen_actual(flujo):
    """Porcentaje del canal más alto ('100%' → 100), o None si pactl no lo da."""
    vals = []
    for canal in (flujo.get('volume') or {}).values():
        m = re.match(r'\s*(\d+)%', str((canal or {}).get('value_percent', '')))
        if m:
            vals.append(int(m.group(1)))
    return max(vals) if vals else None


def flujos_scrcpy():
    """Flujos de audio de scrcpy que suenan en el PC: (lista, '') o (None, error)."""
    if not shutil.which(PACTL_EXEC):
        return None, ('No se encontró pactl, que es lo que cambia el volumen de un programa '
                      'en PipeWire/PulseAudio (en Arch viene en el paquete libpulse). '
                      'Mientras tanto, el mezclador de volumen del escritorio muestra '
                      'scrcpy como una app más.')
    res = run([PACTL_EXEC, '-f', 'json', 'list', 'sink-inputs'], timeout=10)
    if not res['success']:
        return None, res['stderr'] or 'pactl no pudo listar los flujos de audio'
    try:
        datos = json.loads(res['stdout'] or '[]')
    except ValueError:
        return None, 'pactl no devolvió JSON: hace falta PulseAudio 16+ o PipeWire (pipewire-pulse)'
    return [f for f in datos if isinstance(f, dict) and _es_flujo_scrcpy(f)], ''


def act_pc_volume(op, nivel=''):
    """Sube, baja (de 10 en 10) o fija el volumen de scrcpy en el PC, entre 0 y 150 %."""
    if op not in ('subir', 'bajar', 'fijar'):
        return _fail(f'Operación de volumen desconocida: {op}')
    objetivo = None
    if op == 'fijar':
        objetivo = int(_int(nivel, 'Volumen'))
        if not 0 <= objetivo <= _VOL_MAX:
            raise ValueError(f'Volumen fuera de rango: {objetivo} (0-{_VOL_MAX} %)')
    flujos, err = flujos_scrcpy()
    if flujos is None:
        return _fail(err)
    if not flujos:
        return _fail('No suena nada de scrcpy en el PC: abre antes la transmisión. El sonido '
                     'pide Android 11+ y no llega al PC con «Solo en el móvil» ni con '
                     '«Latencia mínima», que va sin audio.')
    hechos = []
    for flujo in flujos:
        idx = str(flujo.get('index'))
        if objetivo is not None:
            nuevo = objetivo
        else:
            actual = _volumen_actual(flujo)
            nuevo = (100 if actual is None else actual) + (_VOL_PASO if op == 'subir' else -_VOL_PASO)
        nuevo = max(0, min(_VOL_MAX, nuevo))
        res = run([PACTL_EXEC, 'set-sink-input-volume', idx, f'{nuevo}%'], timeout=10)
        if not res['success']:
            return _fail(res['stderr'] or f'pactl no pudo cambiar el volumen del flujo {idx}')
        # Subir el volumen de un flujo silenciado no se oiría: se le quita el silencio.
        if nuevo and flujo.get('mute'):
            run([PACTL_EXEC, 'set-sink-input-mute', idx, '0'], timeout=10)
        hechos.append(nuevo)
    log_line(f'volumen scrcpy {op} -> {hechos}')
    return _ok('Volumen de scrcpy en el PC: ' + ', '.join(f'{n} %' for n in hechos) +
               (' (silencio)' if not any(hechos) else ''))


# ----------------------------------------------------------------------
# Teclas mapeadas con QtScrcpy
#
# Los shooters de móvil (Free Fire, CoD Mobile, PUBG…) solo entienden toques: un
# teclado o un ratón «reales» (uhid) no les sirven para andar ni apuntar. Los
# emuladores convierten cada tecla en un toque en su sitio, y eso ya lo hace
# QtScrcpy (Apache-2.0) sobre el móvil de verdad. Gekko ADB no reimplementa ese
# mapeo: lo instala, lo abre y explica cómo se usa. QtScrcpy no acepta
# argumentos (ni siquiera el serial): el móvil se elige en su propia ventana.
#
# El paquete de Chaotic AUR fija QTSCRCPY_ADB_PATH=/usr/bin/adb, el mismo adb
# que usa Gekko ADB: no hay choque de versiones que reinicie el servidor adb y
# tire la conexión por Wi-Fi.

QTSCRCPY_EXEC = (os.environ.get('GEKKO_QTSCRCPY_EXECUTABLE') or shutil.which('qtscrcpy')
                 or shutil.which('QtScrcpy') or 'qtscrcpy')
QTSCRCPY_PAQUETE = 'qtscrcpy'
QTSCRCPY_RELEASES = 'https://github.com/barry-ran/QtScrcpy/releases'
DATA_HOME = Path(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')))
# QStandardPaths::AppDataLocation de QtScrcpy (organización y aplicación «QtScrcpy»).
QTSCRCPY_KEYMAP_DIR = DATA_HOME / 'QtScrcpy' / 'QtScrcpy' / 'keymap'
QTSCRCPY_LOG = LOG_DIR / 'qtscrcpy.log'

_QTSCRCPY_PASOS = (
    'Cómo jugar con teclas mapeadas:\n'
    '  1. En QtScrcpy elige tu móvil: el serial si va por USB, o la IP:puerto si va por Wi-Fi.\n'
    '  2. Elige el mapa de teclas del juego (los .json de la lista de keymaps).\n'
    '  3. Arranca la transmisión desde QtScrcpy.\n'
    '  4. En la ventana del juego, la tecla del mapa (switchKey; en los de ejemplo es `, a la\n'
    '     izquierda del 1 en un teclado inglés) activa o quita el mapeo. Si con tu teclado no\n'
    '     responde, cámbiala en el .json.\n'
    '⚠ En juegos competitivos, mapear teclas a toques puede ir contra sus normas y costar la cuenta.')
_QTSCRCPY_A_MANO = f'    sudo pacman -S --needed {QTSCRCPY_PAQUETE}'


def act_qtscrcpy():
    """Abre QtScrcpy desacoplado; espera 1,5 s para detectar un fallo inmediato."""
    if not shutil.which(QTSCRCPY_EXEC):
        return _fail('QtScrcpy no está instalado. Pulsa «Instalar QtScrcpy» (Arch con Chaotic AUR) '
                     f'o descarga su AppImage de {QTSCRCPY_RELEASES}.')
    # Su salida va a un archivo y no a un pipe: QtScrcpy escribe mucho log y,
    # con un pipe que nadie lee, se quedaría bloqueado al llenarlo.
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        salida = open(QTSCRCPY_LOG, 'wb')
    except OSError:
        salida = subprocess.DEVNULL
    try:
        proc = subprocess.Popen([QTSCRCPY_EXEC], stdin=subprocess.DEVNULL, stdout=salida,
                                stderr=salida, start_new_session=True)
    except Exception as e:
        return _fail(str(e))
    finally:
        if salida is not subprocess.DEVNULL:
            salida.close()
    try:
        proc.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        return _ok('QtScrcpy abierto.\n' + _QTSCRCPY_PASOS)
    # Es de instancia única: si ya estaba abierto, el segundo avisa al primero y sale con 0.
    if proc.returncode == 0:
        return _ok('QtScrcpy ya estaba abierto: se ha traído al frente.\n' + _QTSCRCPY_PASOS)
    return _fail(f'QtScrcpy se cerró al arrancar (código {proc.returncode}); el detalle está en {QTSCRCPY_LOG}')


def act_qtscrcpy_install():
    """Instala QtScrcpy desde Chaotic AUR con pkexec (ventana de contraseña)."""
    if shutil.which(QTSCRCPY_EXEC):
        return _ok('QtScrcpy ya está instalado: pulsa «Jugar con teclas mapeadas».')
    if not shutil.which('pacman'):
        return _fail('Instalarlo desde aquí solo funciona en Arch y derivadas (pacman con Chaotic AUR). '
                     f'En otras distros usa el AppImage de {QTSCRCPY_RELEASES}.')
    if not run(['pacman', '-Si', QTSCRCPY_PAQUETE], timeout=30)['success']:
        return _fail(f'El paquete {QTSCRCPY_PAQUETE} no está en tus repositorios: hace falta Chaotic AUR '
                     f'(GekkoApp lo activa en un clic) o el AppImage de {QTSCRCPY_RELEASES}.')
    if not shutil.which('pkexec'):
        return _fail('Falta pkexec para pedir la contraseña. Instálalo en una terminal:\n' + _QTSCRCPY_A_MANO)
    res = run(['pkexec', 'pacman', '-S', '--needed', '--noconfirm', QTSCRCPY_PAQUETE], timeout=1800)
    if res['success']:
        res['stdout'] = ((res['stdout'] + '\n') if res['stdout'] else '') + \
            'QtScrcpy instalado: pulsa «Jugar con teclas mapeadas».'
        return res
    # Sin agente de polkit (algunos Hyprland/Niri) pkexec no puede pedir la
    # contraseña; lo que falle, la terminal sigue siendo la salida.
    res['stderr'] = ((res['stderr'] or 'pacman no pudo instalar QtScrcpy') +
                     '\nSi no apareció la ventana de contraseña, instálalo en una terminal:\n' +
                     _QTSCRCPY_A_MANO)
    return res


def act_qtscrcpy_keymaps():
    """Abre en el gestor de archivos la carpeta de mapas de teclas de QtScrcpy."""
    if not QTSCRCPY_KEYMAP_DIR.is_dir():
        return _fail(f'Todavía no existe {QTSCRCPY_KEYMAP_DIR}: QtScrcpy la crea, con mapas de '
                     'ejemplo, la primera vez que lo abres.')
    explicacion = ('Cada .json es un juego: las posiciones van de 0 a 1 sobre la pantalla '
                   '(0,5 = el centro) y switchKey es la tecla que activa el mapeo.')
    if not shutil.which('xdg-open'):
        return _ok(f'Tus mapas de teclas están en {QTSCRCPY_KEYMAP_DIR}. {explicacion}')
    try:
        subprocess.Popen(['xdg-open', str(QTSCRCPY_KEYMAP_DIR)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:
        return _fail(str(e))
    return _ok(f'Abriendo {QTSCRCPY_KEYMAP_DIR}. {explicacion}')


# ----------------------------------------------------------------------
# Abrir el juego solo al conectar el móvil
#
# «Conectar» es pasar de no tener ningún móvil listo a tener alguno. Así no
# salta al pasar del cable a la Wi-Fi (el móvil sigue conectado todo el rato) ni
# se repite mientras siga enchufado; sí vuelve a saltar si se desconecta y vuelve.

AUTO_CONECTAR = {'': 'No hacer nada', 'gaming': 'Abrir Gaming', 'qtscrcpy': 'Abrir QtScrcpy'}
# El primero que el móvil y el scrcpy del PC admitan: con mando si se puede.
_AUTO_GAMING = ('game_pad', 'game_kbm')


class AutoArranque:
    """Decide cuándo abrir el juego solo. No sabe nada de GTK ni de adb."""

    def __init__(self):
        self._habia = False

    def armar(self, conectado):
        """Al activar la opción, lo que ya estaba conectado no cuenta como «conectar»."""
        self._habia = bool(conectado)

    def actualizar(self, conectado):
        """True justo cuando el móvil acaba de aparecer."""
        conectado = bool(conectado)
        aparece = conectado and not self._habia
        self._habia = conectado
        return aparece


def spec_auto_conectar(modo, catalogo, info=None):
    """(spec, valores por defecto) que abre «Al conectar», o (None, {}) si no hay nada que abrir."""
    cmds = {c['id']: c for k in (catalogo or {}).get('categorias', []) for c in k.get('comandos', [])}
    if modo == 'qtscrcpy':
        candidatos = ('game_qtscrcpy',)
    elif modo == 'gaming':
        candidatos = _AUTO_GAMING
    else:
        return None, {}
    for cid in candidatos:
        spec = cmds.get(cid)
        if spec and compatibilidad(spec, info)[0]:
            return spec, {c['clave']: c.get('defecto', '') for c in spec.get('campos') or []}
    return None, {}


def act_devices_ready():
    """Sondeo ligero para «Al conectar»: solo `adb devices`, nada que toque el móvil."""
    listos = get_devices()
    return {'success': True, 'stdout': '', 'stderr': '', 'info': {'listos': listos}}


# ----------------------------------------------------------------------
# Rendimiento y juegos: Android Game Mode, tasa de refresco y dexopt
#
# TRAMPA de 'cmd game': solo acepta apps declaradas como juego
# (android:appCategory="game" en el manifiesto). Con cualquier otra imprime
# "Package X is not of game type…" y SALE CON CÓDIGO 0, así que sin leer la
# salida el botón parecería haber funcionado.

_GAME_MODES = ('standard', 'performance', 'battery')
_GAME_LISTS = {'modes': 'list-modes', 'configs': 'list-configs'}
# Valores admitidos por 'cmd game set --downscale' (los imprime su propia ayuda).
_GAME_DOWNSCALE = ('0.3', '0.35', '0.4', '0.45', '0.5', '0.55', '0.6', '0.65',
                   '0.7', '0.75', '0.8', '0.85', '0.9', 'disable')
_GAME_NO_ES_JUEGO = 'is not of game type'


def _game_result(res):
    """Convierte el rechazo silencioso de 'cmd game' en un fallo visible."""
    salida = (res['stdout'] + '\n' + res['stderr'])
    if _GAME_NO_ES_JUEGO in salida:
        res['success'] = False
        res['stderr'] = (salida.strip() +
                         '\n→ Solo las apps con android:appCategory="game" en su '
                         'manifiesto aceptan los comandos de modo de juego.')
    return res


def act_game_mode(mode, package):
    """cmd game mode <standard|performance|battery> <paquete>."""
    return _game_result(run_adb(['shell', 'cmd', 'game', 'mode',
                                 _opcion(mode, 'modo de juego', _GAME_MODES),
                                 _package(package)]))


def act_game_list(what, package):
    """cmd game list-modes / list-configs <paquete>."""
    sub = _GAME_LISTS.get(what)
    if sub is None:
        return _fail(f'Listado de modo de juego desconocido: {what}')
    return _game_result(run_adb(['shell', 'cmd', 'game', sub, _package(package)]))


def act_game_reset(package):
    """cmd game reset <paquete>: devuelve la app a la configuración del móvil."""
    return _game_result(run_adb(['shell', 'cmd', 'game', 'reset', _package(package)]))


def act_game_set(downscale, fps, package):
    """cmd game set [--downscale X] [--fps N] <paquete> (modo 'custom')."""
    package = _package(package)
    args = ['shell', 'cmd', 'game', 'set']
    if downscale is not None and str(downscale).strip():
        args += ['--downscale', _opcion(downscale, 'reescalado', _GAME_DOWNSCALE)]
    if fps is not None and str(fps).strip():
        # Cota superior como en sus vecinos (tasa de refresco 1-480, brillo 0-100):
        # 0 quita el tope, y un valor absurdo no tiene por qué llegar al móvil.
        args += ['--fps', _sc_uint(fps, 'FPS', maximo=1000)]
    if len(args) == 4:
        return _fail('Indica al menos un ajuste: reescalado o FPS')
    return _game_result(run_adb(args + [package]))


# min_refresh_rate y peak_refresh_rate viven en el espacio 'system' y van
# siempre en pareja: fijar solo el pico deja al móvil bajar la tasa igual.
_REFRESH_KEYS = ('min_refresh_rate', 'peak_refresh_rate')


def act_refresh_rate(op, hz=''):
    """Fija, lee o borra las dos claves de tasa de refresco.

    'delete' es la forma correcta de restablecer: sin override el sistema
    vuelve a decidir (settings get devuelve 'null', que es como vienen de
    fábrica). Escribir un número "por defecto" a mano dejaría clavada una tasa
    que no tiene por qué ser la del móvil.
    """
    if op not in ('put', 'get', 'delete'):
        return _fail(f'Operación de tasa de refresco desconocida: {op}')
    if op == 'put':
        hz = _sc_uint(hz, 'Tasa de refresco')
        if not 1 <= int(hz) <= 480:
            return _fail(f'Tasa de refresco fuera de rango (1-480 Hz): {hz}')
    lineas, ok = [], True
    for key in _REFRESH_KEYS:
        args = ['shell', 'settings', op, 'system', key] + ([hz] if op == 'put' else [])
        res = run_adb(args)
        ok = ok and res['success']
        salida = (res['stdout'].strip() or res['stderr'].strip() or 'OK')
        lineas.append(f'{key}: {salida}')
    if ok and op == 'put':
        lineas.append(f'Tasa de refresco forzada a {hz} Hz. Para volver al automático, '
                      '«Restablecer la tasa de refresco» (settings delete).')
    return {'success': ok, 'stdout': '\n'.join(lineas),
            'stderr': '' if ok else 'settings falló en alguna de las dos claves'}


# 'cmd package compile' es el dexopt manual: recompila el bytecode de la app.
_COMPILE_FILTERS = ('speed', 'speed-profile', 'verify')


def act_pkg_compile(package, filtro='speed', reset=False):
    """cmd package compile -m <filtro> -f <paquete> (o --reset para deshacer)."""
    package = _package(package)
    if reset:
        args = ['shell', 'cmd', 'package', 'compile', '--reset', package]
    else:
        args = ['shell', 'cmd', 'package', 'compile', '-m',
                _opcion(filtro, 'filtro de compilación', _COMPILE_FILTERS), '-f', package]
    return _pm_result(run_adb(args, timeout=900))


def act_device_info():
    info = get_device_info()
    if not info['connected']:
        return {'success': False, 'stdout': '', 'stderr': info['message'], 'info': info}
    lines = [f"{k}: {v}" for k, v in info.items() if k not in ('connected',)]
    return {'success': True, 'stdout': '\n'.join(lines), 'stderr': '', 'info': info}


# ----------------------------------------------------------------------
# Despacho de acciones del catálogo
#
# Cada entrada del catálogo usa 'accion' + 'args' (fijos) + 'campos'
# (pedidos en el diálogo de la UI). build_valores une args fijos, valores
# de la UI y flags en un solo dict `v`; las lambdas SOLO leen de `v`.

_ACTIONS = {
    'devices': lambda v: act_devices(),
    'version': lambda v: act_version(),
    'start_server': lambda v: act_start_server(),
    'kill_server': lambda v: act_kill_server(),
    'host_features': lambda v: act_host_features(),
    'help': lambda v: act_help(),
    'tcpip': lambda v: act_tcpip(v.get('port')),
    'connect': lambda v: act_connect(v.get('ip')),
    'disconnect': lambda v: act_disconnect(v.get('ip', '')),
    'pair': lambda v: act_pair(v.get('ip'), v.get('code')),
    'reconnect': lambda v: act_reconnect(v.get('target', '')),
    'usb': lambda v: act_usb(),
    'mdns_check': lambda v: act_mdns_check(),
    'mdns_services': lambda v: act_mdns_services(),
    'device_ip': lambda v: act_device_ip(),
    'wifi_auto': lambda v: act_wifi_auto(v.get('port', '5555')),
    'get_state': lambda v: act_get_state(),
    'wait_for_device': lambda v: act_wait_for_device(),
    'push': lambda v: act_push(v.get('origen'), v.get('destino')),
    'pull': lambda v: act_pull(v.get('origen'), v.get('destino')),
    'pull_merge': lambda v: act_pull_merge(v.get('origen'), v.get('destino')),
    'sync_push': lambda v: act_sync_push(v.get('origen'), v.get('destino')),
    'quick_pull': lambda v: act_quick_pull(v['origen'], v['destino'], v.get('sub', '')),
    'install': lambda v: act_install(v.get('apk'), v.get('flags', [])),
    'install_multiple': lambda v: act_install_multiple(v.get('apks'), v.get('flags', [])),
    'install_multi_package': lambda v: act_install_multi_package(v.get('apks'), v.get('flags', [])),
    'uninstall': lambda v: act_uninstall(v.get('package'), v.get('flags', [])),
    'restore': lambda v: act_restore(v.get('package')),
    'extract_apk': lambda v: act_extract_apk(v.get('package')),
    'sideload': lambda v: act_sideload(v.get('ota')),
    'forward_list': lambda v: act_forward_list(),
    'forward_add': lambda v: act_forward_add(v.get('local'), v.get('remoto')),
    'forward_remove_all': lambda v: act_forward_remove_all(),
    'reverse_list': lambda v: act_reverse_list(),
    'reverse_add': lambda v: act_reverse_add(v.get('remoto'), v.get('local')),
    'reverse_remove_all': lambda v: act_reverse_remove_all(),
    'reboot': lambda v: act_reboot(v.get('mode', 'normal')),
    'soft_reboot': lambda v: act_reboot('soft'),
    'root': lambda v: act_root(),
    'unroot': lambda v: act_unroot(),
    'remount': lambda v: act_remount(),
    'bugreport': lambda v: act_bugreport(),
    'custom': lambda v: act_custom(v.get('command')),
    'terminal': lambda v: act_custom(v.get('command')),
    'getprop': lambda v: act_getprop(v.get('key', '')),
    'setprop': lambda v: act_setprop(v.get('key'), v.get('value')),
    'pm_action': lambda v: act_pm_action(v.get('action'), v.get('package'), v.get('permission')),
    'debloat_preset': lambda v: act_debloat_preset(v['preset']),
    'restore_preset': lambda v: act_restore_preset(v['preset']),
    'list_packages': lambda v: act_list_packages(v.get('filtro', '-u')),
    'appops_get': lambda v: act_appops_get(v.get('package'), v.get('op', '')),
    'appops_set': lambda v: act_appops_set(v.get('package'), v.get('op'), v.get('mode')),
    'settings_put': lambda v: act_settings_put(v.get('space'), v.get('key'), v.get('value')),
    'settings_get': lambda v: act_settings_get(v.get('space'), v.get('key')),
    'settings_list': lambda v: act_settings_list(v.get('space')),
    'settings_delete': lambda v: act_settings_delete(v.get('space'), v.get('key')),
    'nav_mode': lambda v: act_nav_mode(v.get('mode')),
    'anim_scale': lambda v: act_anim_scale(v.get('scale')),
    'density': lambda v: act_density(v.get('dpi')),
    'density_reset': lambda v: act_density_reset(),
    'wm_size': lambda v: act_wm_size(v.get('size')),
    'wm_size_reset': lambda v: act_wm_size_reset(),
    'brightness_get': lambda v: act_brightness_get(),
    'brightness_set': lambda v: act_brightness_set(v.get('nivel')),
    'rotation': lambda v: act_rotation(v.get('mode', 'auto')),
    'role_set': lambda v: act_role_set(v.get('role', 'android.app.role.HOME'), v.get('package', '')),
    'role_list': lambda v: act_role_list(),
    'input_key': lambda v: act_input_key(v.get('key')),
    'input_text': lambda v: act_input_text(v.get('text')),
    'input_tap': lambda v: act_input_tap(v.get('x'), v.get('y')),
    'input_swipe': lambda v: act_input_swipe(v.get('x1'), v.get('y1'), v.get('x2'), v.get('y2'), v.get('dur')),
    'dumpsys': lambda v: act_dumpsys(v.get('servicio'), v.get('extra')),
    'dumpsys_package': lambda v: act_dumpsys_package(v.get('package')),
    'dumpsys_app': lambda v: act_dumpsys_app(v.get('servicio'), v.get('package')),
    'battery_cmd': lambda v: act_battery_cmd(v.get('cmd')),
    'top': lambda v: act_top(),
    'logcat_read': lambda v: act_logcat_read(v.get('level', 'V'), v.get('filter', '')),
    'logcat_clear': lambda v: act_logcat_clear(),
    'processes': lambda v: act_processes(),
    'screenshot': lambda v: act_screenshot(),
    'screenrecord': lambda v: act_screenrecord(v.get('seconds', '10')),
    'storage': lambda v: act_storage(),
    'ime_list': lambda v: act_ime_list(),
    'ime_set': lambda v: act_ime_set(v.get('ime')),
    'app_launch': lambda v: act_app_launch(v.get('package')),
    'app_info': lambda v: act_app_info(v.get('package')),
    'open_url': lambda v: act_open_url(v.get('url')),
    'am_start': lambda v: act_am_start(v.get('intent')),
    'overlay_list': lambda v: act_overlay_list(),
    'overlay_enable': lambda v: act_overlay_toggle(v.get('package'), True),
    'overlay_disable': lambda v: act_overlay_toggle(v.get('package'), False),
    'svc': lambda v: act_svc(v.get('what')),
    'netpolicy': lambda v: act_netpolicy(v.get('what')),
    'netpolicy_restrict': lambda v: act_netpolicy_restrict(v.get('estado')),
    'statusbar': lambda v: act_statusbar(v.get('what')),
    'scrcpy': lambda v: act_scrcpy(v.get('mode', 'standard'), v),
    'scrcpy_game': lambda v: act_scrcpy_game(v),
    'scrcpy_list': lambda v: act_scrcpy_list(v.get('what')),
    'pc_volume': lambda v: act_pc_volume(v.get('op'), v.get('nivel', '')),
    'qtscrcpy': lambda v: act_qtscrcpy(),
    'qtscrcpy_install': lambda v: act_qtscrcpy_install(),
    'qtscrcpy_keymaps': lambda v: act_qtscrcpy_keymaps(),
    'devices_ready': lambda v: act_devices_ready(),
    'game_mode': lambda v: act_game_mode(v.get('mode'), v.get('package')),
    'game_list': lambda v: act_game_list(v.get('what'), v.get('package')),
    'game_reset': lambda v: act_game_reset(v.get('package')),
    'game_set': lambda v: act_game_set(v.get('downscale', ''), v.get('fps', ''), v.get('package')),
    'refresh_rate': lambda v: act_refresh_rate(v.get('op', 'get'), v.get('hz', '')),
    'pkg_compile': lambda v: act_pkg_compile(v.get('package'), v.get('filtro', 'speed'),
                                             bool(v.get('reset'))),
    'device_info': lambda v: act_device_info(),
}


def build_valores(spec, valores_ui, flags_ui):
    """Une args fijos + valores de la UI + flags en {clave: valor} para el dispatch."""
    campos = {c['clave']: c for c in spec.get('campos', [])}
    valores = {}
    for clave, val in (spec.get('args') or {}).items():
        valores[clave] = val
    for clave, val in (valores_ui or {}).items():
        if clave in campos or spec.get('accion') in ('custom', 'terminal'):
            valores[clave] = val
    valores['flags'] = list(flags_ui or [])
    return valores


def validar_campos(spec, valores):
    """Comprueba campos obligatorios y numéricos antes de ejecutar. Devuelve lista de errores."""
    errores = []
    for campo in spec.get('campos') or []:
        clave = campo['clave']
        val = valores.get(clave)
        vacio = val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, list) and not val)
        if vacio:
            if not campo.get('opcional'):
                errores.append(f"Falta el valor: {campo.get('etiqueta', clave)}")
            continue
        if campo.get('tipo') == 'numero' and not _INT_RE.match(str(val).strip()):
            errores.append(f"{campo.get('etiqueta', clave)} debe ser un número entero")
    return errores


def ejecutar(spec, valores_ui=None, flags_ui=None):
    """Ejecuta una especificación del catálogo. Devuelve dict resultado."""
    accion = spec.get('accion')
    if accion is None:
        return _fail('Sin acción definida')
    handler = _ACTIONS.get(accion)
    if handler is None:
        return _fail(f'Acción desconocida: {accion}')
    try:
        valores = build_valores(spec, valores_ui, flags_ui)
        errores = validar_campos(spec, valores)
        if errores:
            return _fail('\n'.join(errores))
        return handler(valores)
    except KeyError as e:
        return _fail(f'Falta el valor: {e}')
    except ValueError as e:
        return _fail(str(e))
    except Exception as e:
        log_line(f'excepción en {accion}: {e!r}', force=True)
        return _fail(f'{type(e).__name__}: {e}')


class CommandWorker(threading.Thread):
    """Ejecuta una especificación del catálogo en segundo plano.

    Contrato: exactamente un callback terminal — `on_done(result)` con
    cualquier resultado (success True o False), o `on_error(err)` solo si
    el hilo abortó por excepción. Los callbacks se invocan desde el hilo
    del worker; la UI debe aplicar el resultado con GLib.idle_add.
    """

    def __init__(self, spec, valores_ui=None, flags_ui=None, on_done=None, on_error=None):
        super().__init__(daemon=True)
        self.spec = spec
        self._valores = valores_ui or {}
        self._flags = flags_ui or []
        self._on_done = on_done
        self._on_error = on_error
        self._finished = False
        self._cancelado = False
        self._ident = None
        self.result = None

    def cancel(self):
        """Cancela el comando en curso. Es seguro llamarla siempre.

        Si el proceso ya terminó no hay nada que matar y no lanza; si aún no ha
        arrancado, `run()` lo verá al empezar y no llegará a ejecutar nada.
        """
        self._cancelado = True
        ident = self._ident
        if ident is not None:
            cancelar_hilo(ident)
        return True

    @staticmethod
    def _resultado_cancelado():
        return {'success': False, 'cancelled': True, 'stdout': '',
                'stderr': 'Cancelado por el usuario'}

    def _terminar(self, result):
        """Entrega el único callback terminal del contrato."""
        if self._finished:
            return
        self._finished = True
        self.result = result
        if self._on_done:
            try:
                self._on_done(result)
            except Exception as cb:
                log_line(f'on_done falló: {cb!r}', force=True)

    def run(self):
        self._ident = threading.get_ident()
        limpiar_cancelado(self._ident)
        # Cancelado entre start() y la primera línea del hilo: no se ejecuta nada.
        if self._cancelado:
            self._terminar(self._resultado_cancelado())
            return
        try:
            result = ejecutar(self.spec, self._valores, self._flags)
        except Exception as e:
            limpiar_cancelado(self._ident)
            # Matar el proceso hace que adb salga con error: si veníamos de una
            # cancelación, eso NO es un fallo real y se informa como cancelado.
            if self._cancelado:
                self._terminar(self._resultado_cancelado())
                return
            if not self._finished:
                self._finished = True
                if self._on_error:
                    try:
                        self._on_error(e)
                    except Exception as cb:
                        log_line(f'on_error falló: {cb!r}', force=True)
            return
        limpiar_cancelado(self._ident)
        if self._cancelado:
            result = self._resultado_cancelado()
        self._terminar(result)


def start_command(spec, valores_ui=None, flags_ui=None, on_done=None, on_error=None):
    worker = CommandWorker(spec, valores_ui, flags_ui, on_done, on_error)
    worker.start()
    return worker


# ----------------------------------------------------------------------
# Catálogo, presets y configuración

class CatalogoError(Exception):
    pass


def load_catalogo():
    try:
        with open(CATALOGO_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise CatalogoError(f'No se pudo leer {CATALOGO_FILE}: {e}')
    cats = data.get('categorias')
    if not isinstance(cats, list):
        raise CatalogoError(f'{CATALOGO_FILE}: falta la lista "categorias"')
    vistos = {}
    for c in cats:
        if not isinstance(c, dict) or 'id' not in c or 'titulo' not in c:
            raise CatalogoError(f'{CATALOGO_FILE}: categoría sin id/titulo: {c!r}')
        c.setdefault('comandos', [])
        for cmd in c['comandos']:
            if 'id' not in cmd or 'accion' not in cmd:
                raise CatalogoError(f'{CATALOGO_FILE}: comando sin id/accion en {c["id"]}: {cmd!r}')
            cmd.setdefault('titulo', cmd['id'])
            if cmd['id'] in vistos:
                raise CatalogoError(
                    f'{CATALOGO_FILE}: id de comando duplicado «{cmd["id"]}» '
                    f'(en «{vistos[cmd["id"]]}» y en «{c["id"]}»)')
            vistos[cmd['id']] = c['id']
            _validar_comando(c, cmd)
    return data


# Tipos de campo que las DOS interfaces saben pintar (gekko-adb-gtk4.py y
# gekko-adb-gtk3.py, _build_campo_widget). Uno fuera de esta lista se pintaría
# como texto plano y el usuario perdería el selector sin enterarse.
TIPOS_CAMPO = frozenset({'texto', 'numero', 'select', 'paquete',
                         'archivo', 'archivos', 'carpeta'})

# Acciones que NO cambian nada en el móvil: consultan, listan o se traen algo al
# PC. El resto se considera que muta, así que una acción nueva nace clasificada
# como mutante hasta que alguien la declare de lectura a conciencia: el olvido
# cae del lado seguro, que es justo lo que aquí interesa.
ACCIONES_LECTURA = frozenset({
    'appops_get', 'brightness_get', 'bugreport', 'device_info', 'device_ip',
    'devices', 'devices_ready', 'dumpsys', 'dumpsys_app', 'dumpsys_package',
    'extract_apk', 'forward_list', 'game_list', 'get_state', 'getprop', 'help',
    'host_features', 'ime_list', 'list_packages', 'logcat_read', 'mdns_check',
    'mdns_services', 'netpolicy', 'overlay_list', 'processes', 'pull', 'pull_merge',
    'qtscrcpy_keymaps', 'quick_pull', 'reverse_list', 'role_list', 'screenshot',
    'scrcpy_list', 'settings_get', 'settings_list', 'storage', 'top', 'version',
    'wait_for_device',
})

# De las que mutan, estas pueden dejar el móvil inservible, borrar datos, cortar
# la propia conexión o tardar minutos. La interfaz exige confirmación para ellas
# AUNQUE el comando del catálogo se olvide de pedirla: así el hueco no depende de
# acordarse de escribir "confirmar" en el JSON, que es de donde salieron los
# botones sin red que encontró la auditoría (pm_disable, settings_put, sideload…).
# Solo entran las acciones peligrosas SIEMPRE, pasen los argumentos que pasen.
# Las que dependen del argumento (pm_action vale para «desactivar» y para
# «reactivar»; svc apaga el Wi-Fi o lo enciende; refresh_rate fija o consulta)
# se quedan fuera a propósito: forzarlas aquí obligaría a confirmar también su
# variante inofensiva y volvería insoportable una app que hoy es de un clic.
# Para esas, la red la pone el propio comando en el JSON y la vigila el test de
# integridad de test_core.py, que es el que impide que se olvide.
ACCIONES_CRITICAS = frozenset({
    'debloat_preset', 'density', 'install', 'install_multi_package',
    'install_multiple', 'overlay_disable', 'overlay_enable', 'reboot',
    'remount', 'restore_preset', 'root', 'settings_delete', 'settings_put',
    'setprop', 'sideload', 'soft_reboot', 'uninstall', 'unroot', 'wm_size',
})


# Compatibilidad declarada por botón: {"requiere": {"sdk": 31, "scrcpy": "3.1"}}
# «sdk» es la API de Android (12 = 31, 13 = 33, 14 = 34) y «scrcpy» la versión
# mínima del binario del PC. Decirlo ANTES de pulsar evita el peor caso: un
# botón que falla con un error de adb que no explica que el móvil es antiguo.
_scrcpy_ver_cache = {'v': None, 'leido': False}


def scrcpy_version():
    """Versión de scrcpy instalada como tupla (4, 1), o None si no se sabe.

    Se cachea: esto se consulta al pintar cada tarjeta y lanzar scrcpy por cada
    botón sería absurdo.
    """
    if _scrcpy_ver_cache['leido']:
        return _scrcpy_ver_cache['v']
    _scrcpy_ver_cache['leido'] = True
    if shutil.which(SCRCPY_EXEC):
        res = run([SCRCPY_EXEC, '--version'], timeout=10)
        m = re.search(r'scrcpy\s+(\d+)\.(\d+)', res.get('stdout', '') or '')
        if m:
            _scrcpy_ver_cache['v'] = (int(m.group(1)), int(m.group(2)))
    return _scrcpy_ver_cache['v']


def _ver_tupla(texto):
    partes = re.findall(r'\d+', str(texto))[:2]
    return tuple(int(p) for p in partes) if partes else None


def compatibilidad(spec, info=None):
    """Dice si el comando puede funcionar aquí: (compatible, motivo).

    `compatible` es True cuando no hay impedimento conocido y False solo cuando
    consta que NO va a funcionar. Si falta el dato (sin móvil conectado, o
    scrcpy sin instalar) devuelve True con el motivo en None: avisar en falso es
    peor que no avisar, porque el usuario deja de fiarse del aviso.
    """
    req = (spec or {}).get('requiere') or {}
    if not req:
        return True, None
    sdk_min = req.get('sdk')
    if sdk_min:
        sdk = (info or {}).get('sdk')
        try:
            sdk = int(sdk)
        except (TypeError, ValueError):
            sdk = None
        if sdk and sdk < int(sdk_min):
            return False, (f'Necesita Android {_ANDROID_POR_SDK.get(int(sdk_min), "?")} '
                           f'(API {sdk_min}) y el móvil tiene API {sdk}')
    ver_min = req.get('scrcpy')
    if ver_min:
        v = scrcpy_version()
        minimo = _ver_tupla(ver_min)
        if v and minimo and v < minimo:
            return False, (f'Necesita scrcpy {ver_min} y hay '
                           f'{v[0]}.{v[1]} instalado')
    return True, None


# Solo las que hacen falta para los mensajes; el resto sale como '?'.
_ANDROID_POR_SDK = {29: '10', 30: '11', 31: '12', 32: '12L', 33: '13', 34: '14',
                    35: '15', 36: '16'}


def es_lectura(spec):
    """True si el comando solo consulta: nunca debe pedir confirmación."""
    return (spec or {}).get('accion') in ACCIONES_LECTURA


def necesita_confirmacion(spec):
    """Si hay que preguntar antes de ejecutar este comando del catálogo.

    Manda lo que diga el comando, y si no dice nada decide la acción: las
    críticas confirman por omisión. Un comando puede renunciar a propósito con
    "confirmar": false, pero entonces es una decisión escrita, no un descuido.
    """
    spec = spec or {}
    if 'confirmar' in spec:
        return bool(spec['confirmar'])
    if es_lectura(spec):
        return False
    return spec.get('accion') in ACCIONES_CRITICAS


def _validar_comando(cat, cmd):
    """Comprueba un comando del catálogo. Lanza CatalogoError con el sitio exacto.

    Se ejecuta al arrancar y aborta la app a propósito: el catálogo lo controla
    el proyecto, así que un fallo aquí es un bug que hay que ver de inmediato,
    no un dato del usuario que convenga tolerar. Cada mensaje dice categoría,
    comando y campo para poder arreglarlo sin buscar.
    """
    donde = f'{CATALOGO_FILE}: {cat["id"]} → {cmd["id"]}'
    if cmd['accion'] not in _ACTIONS:
        raise CatalogoError(f'{donde}: acción desconocida «{cmd["accion"]}»')
    for campo in cmd.get('campos') or []:
        if not isinstance(campo, dict) or not campo.get('clave'):
            raise CatalogoError(f'{donde}: campo sin «clave»: {campo!r}')
        clave = campo['clave']
        tipo = campo.get('tipo', 'texto')
        if tipo not in TIPOS_CAMPO:
            raise CatalogoError(
                f'{donde} → {clave}: tipo «{tipo}» que las interfaces no saben pintar '
                f'(admitidos: {", ".join(sorted(TIPOS_CAMPO))})')
        if tipo != 'select':
            continue
        opciones = campo.get('opciones')
        if not opciones:
            raise CatalogoError(f'{donde} → {clave}: un select necesita «opciones»')
        valores = [op.get('valor') for op in opciones]
        defecto = campo.get('defecto', '')
        if defecto not in valores:
            raise CatalogoError(
                f'{donde} → {clave}: el defecto «{defecto}» no está entre sus opciones '
                f'({", ".join(repr(v) for v in valores)})')
        # El fallo que dejaba «Reconectar» y «Listar paquetes → Instaladas» rotos de
        # fábrica: validar_campos() rechaza el vacío de un campo no opcional, así que
        # un select con una opción vacía SIEMPRE fallaba al elegirla.
        if not campo.get('opcional') and any(v in (None, '') for v in valores):
            raise CatalogoError(
                f'{donde} → {clave}: tiene una opción de valor vacío pero no es '
                f'«opcional»: elegirla daría siempre «Falta el valor»')


def load_presets():
    try:
        with open(PRESETS_FILE, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise CatalogoError(f'No se pudo leer {PRESETS_FILE}: {e}')
    presets = []
    for p in data.get('presets', []):
        if not isinstance(p, dict) or not p.get('id') or not p.get('titulo'):
            log_line(f'preset ignorado (sin id/titulo): {p!r}', force=True)
            continue
        try:
            _preset_packages(p)
        except ValueError as e:
            log_line(f'preset ignorado: {e}', force=True)
            continue
        presets.append(p)
    return presets


def preset_buttons():
    """Convierte cada preset en dos especificaciones ejecutables: aplicar y restaurar."""
    specs = []
    for p in load_presets():
        adv = p.get('advertencia', '')
        specs.append({
            'id': f'preset_{p["id"]}',
            'titulo': f'{p.get("icono", "🧹")} {p["titulo"]}',
            # La advertencia NO se concatena aquí: la tarjeta y el diálogo de
            # confirmación ya leen la clave 'advertencia' por su cuenta, y
            # concatenarla la pintaba dos veces en el mismo botón.
            'desc': p.get('desc', ''),
            'accion': 'debloat_preset',
            'args': {'preset': p},
            'peligro': True,
            'confirmar': True,
            'advertencia': adv,
        })
        specs.append({
            'id': f'restore_{p["id"]}',
            'titulo': f'↩ Restaurar: {p["titulo"]}',
            'desc': f'cmd package install-existing de los {len(p["paquetes"])} paquetes del preset',
            'accion': 'restore_preset',
            'args': {'preset': p},
        })
    return specs


def cargar_config():
    cfg = configparser.ConfigParser()
    cfg['General'] = {'theme': 'system', 'log_enabled': 'false', 'auto_conectar': ''}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding='utf-8') as f:
                cfg.read_file(f)
        except (OSError, configparser.Error) as e:
            log_line(f'config.ini ilegible: {e}', force=True)
    return cfg


def guardar_config(cfg):
    """Devuelve '' si se guardó, o el mensaje de error."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            cfg.write(f)
        set_logging(cfg.getboolean('General', 'log_enabled', fallback=False))
        return ''
    except (OSError, configparser.Error) as e:
        log_line(f'no se pudo guardar config.ini: {e}', force=True)
        return str(e)


def connectividad():
    """Estado rápido para el header de la UI."""
    return get_device_info()


def diagnostics():
    """Texto de diagnóstico y código de salida (0 ok, 1 falta adb)."""
    lines = []
    rc = 0
    adb_path = shutil.which(ADB_EXEC)
    ver = run([ADB_EXEC, 'version'], timeout=15)
    if adb_path and ver['success']:
        lines.append(f'ADB: {adb_path} — {ver["stdout"].splitlines()[0]}')
    else:
        lines.append(f'ADB: NO DISPONIBLE ({ADB_EXEC}): {ver["stderr"] or "instala android-tools"}')
        rc = 1
    scrcpy_path = shutil.which(SCRCPY_EXEC)
    lines.append(f'Scrcpy: {scrcpy_path or "no instalado (opcional)"}')
    gi = run([sys.executable, '-c', "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; print('GTK4 ' + '.'.join(map(str,(Gtk.get_major_version(),Gtk.get_minor_version()))))"], timeout=30)
    gi3 = run([sys.executable, '-c', "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print('GTK3 ' + '.'.join(map(str,(Gtk.get_major_version(),Gtk.get_minor_version()))))"], timeout=30)
    lines.append('GTK: ' + (', '.join(x['stdout'] for x in (gi, gi3) if x['success']) or 'python-gobject/GTK no disponibles'))
    if not gi['success'] and not gi3['success']:
        rc = 1
    if rc == 0:
        devs, res = list_transports(fresh=True)
        if devs:
            lines.append('Dispositivos: ' + ', '.join(f'{s} ({st})' for s, st in devs))
        else:
            lines.append('Dispositivos: (ninguno)')
    return '\n'.join(lines), rc


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='gekko-adb', description=f'{APP_NAME} (núcleo CLI)')
    parser.add_argument('--version', action='store_true', help='mostrar versión')
    parser.add_argument('--diagnostics', action='store_true', help='verificar dependencias y dispositivos')
    parser.add_argument('--json', action='store_true', help='imprimir la información del dispositivo en JSON')
    args = parser.parse_args(argv)
    if args.version:
        print(f'{APP_NAME} {APP_VERSION}')
        return 0
    if args.diagnostics:
        text, rc = diagnostics()
        print(text)
        return rc
    print(json.dumps(connectividad(), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
