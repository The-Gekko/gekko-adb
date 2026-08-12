# Gekko ADB Studio

Master suite de control **ADB** para Linux (Garuda/Arch), nativa GTK. Reemplazó la
app web legacy (`server.py` + `index.html` + Vivaldi, ya eliminada) por una app
nativa con tema **Matugen** dinámico.

## Commands

```bash
python3 -m unittest discover -s . -p 'test_*.py'   # tests (core + tema + GTK3)
python3 -m unittest test_ui_gtk4 -v                # tests GTK4 (no coexiste con GTK3 en el mismo proceso)
./install.sh --check                               # diagnóstico sin escribir
./install.sh                                       # instalar (XDG, nunca root)
./install.sh --uninstall                           # desinstalar (conserva config/logs)
gekko-adb                                          # lanzar la app instalada
./bin/gekko-adb                                    # lanzar desde el checkout (dev)
```

## Work State

### Completed
- [x] Catálogo `adb_commands.json` (servidor USB/Wi-Fi, instalación, transferencia,
      boot, teléfono, ajustes, roles, scrcpy) con campos editables por comando.
- [x] `debloat_presets.json` (presets de desbloqueo, paquetes por preset).
- [x] `gekko_adb_core.py` — núcleo headless sin `gi` (runner ADB, catálogo,
      `CommandWorker` de un solo callback terminal, debloat, logs).
- [x] `gekko_adb_theme.py` — tema dinámico Matugen (fallback system/dark/light).
- [x] Frontend `gekko-adb-gtk4.py` (GTK4) y `gekko-adb-gtk3.py` (GTK3).
- [x] `bin/gekko-adb` — lanzador dev (usa checkout; gecho a instalación).
- [x] `assets/gekko-adb.png` — ícono del proyecto (instala `gekko-adb-512.png`
      en hicolor 512x512, nombre de tema `gekko-adb`).
- [x] `install.sh` — instalador Arch/Garuda (pacman) y Solus (eopkg, paquetes
      `libgtk-3`/`libgtk-4`): dependencias, launcher en `~/.local/bin`, desktop
      entry `com.gekko.adb`, ícono hicolor, metainfo, backup/rollback,
      `--uninstall`, `--check`.
- [x] Selector de archivos GTK4 con `Gtk.FileDialog` (async, no `run()`); el de
      GTK3 usa `Gtk.FileChooserDialog.run()`.
- [x] Dashboard multi-marca: `get_device_info()` devuelve `marca`
      (samsung/xiaomi/other) y `secure` (Knox para Samsung, Bootloader+Verified
      para Xiaomi/Redmi/Poco, SELinux para genérico).
- [x] Presets debloat Xiaomi/Redmi (`xiaomi_basic`, `hyperos_ai`, `miui_stock`)
      además de los Samsung; `google_bloat` es multi-marca.
- [x] Comandos de roles Xiaomi (HOME→`com.miui.home`, SMS→`com.android.mms`,
      DIALER→`com.android.dialer`); textos de ejemplo neutrales en el catálogo.
- [x] Tests: `test_core.py`, `test_theme.py`, `test_ui_gtk3.py`, `test_ui_gtk4.py`
      (SKIP en UI si no hay display; GTK4 aparte — no coexiste con GTK3).

### Completed
- [x] Instalar vía `install.sh` en `~/.local/share/gekko-adb/app`, launcher
      `~/.local/bin/gekko-adb`, desktop entry `com.gekko.adb`, reemplazo del
      launcher web legacy `GekkoADB.desktop`.
- [x] Verificar en hardware real (SM-S928B, Android 16/API 36): dashboard con
      datos del dispositivo, tema matugen, sin errores al abrir.

### Completed
- [x] Corregido el parseo de batería en `get_device_info()`: antes matcheaba substrings
      (`'level:' in line`) sobre todo el output de `dumpsys battery` — incluyendo
      `[EventLogBuffer]` y timestamps — dando basura (`34%`, `3.4 °C`, `0.034 V`, `Issue`
      en el S24; `-1%` en MIUI por `Capacity level: -1`). Ahora `_parse_battery_state()`
      parsea solo la sección `Current Battery Service state:` con match estricto,
      `-1`/`null`→`N/A`, normaliza `level` con `scale` y mapea `status`/`health`.
- [x] Cadena de fallback de batería: `dumpsys battery` → `dumpsys batteryproperties`
      → sysfs `/sys/class/power_supply/battery/*` (best-effort; S24 no expone sysfs).
- [x] Endurecidos `wm size`/`wm density` (Override > Forced > Physical vía `_wm_value`),
      `nav_mode` (`null`→`Predeterminado`) y `model` (sin doble espacio).
- [x] Fixtures reales en `tests/fixtures/` (dumpsys battery del S24, MIUI con
      `Capacity level: -1`, AOSP con `scale`) + tests de regresión en `test_core.py`
      (fake adb ruidoso que reproduce el bug).
- [x] Verificado en hardware real (SM-S928B): dashboard y core coinciden con los valores
      del Settings del dispositivo (78 %, 36.3 °C, 4.182 V, Cargando, Bien).

### In Progress
- (ninguno)

### Backlog
- [ ] Probar flujos largos (scrcpy, logcat, boot, debloat) con el dispositivo real.
- [ ] Verificar la instalación en Solus (eopkg) en hardware/VM real.

### Checklist de verificación read-only (S24, ADB USB)
Para probar comandos del catálogo sin riesgo, ejecutar estos y confirmar que el
resultado es coherente:
- [ ] `devices`, `version`, `host_features`, `mdns check`, `mdns services`
- [ ] `getprop` (consulta), `getprop <clave>`
- [ ] Roles: `role_holders` (lectura de HOME/SMS/DIALER)
- [ ] `dumpsys battery`, `dumpsys meminfo`, `top` (CPU)
- [ ] `list_packages`, `processes`, `logcat_read` (nivel I + filtro), `logcat_clear`
- [ ] `forward --list`, `reverse --list`
- [ ] `screenshot` (captura a Imágenes), `extract_apk` de una app del sistema
- [ ] `scrcpy` estándar y `--record` (cortos), `wm size/density` solo consulta vía
      dashboard (no tocar sin saber restaurar)
- [ ] `restore` de un paquete de stock para validar `install-existing` sin riesgo

Destructivos/cambiantes (requieren confirmar): `install/uninstall`, `pm disable`,
`settings put`, `nav_mode`, `anim_scale`, `density`, `wm_size`, `role_set`, `reboot`,
`root/remount`, `debloat_preset`, `push/pull/sync/quick_pull`, `tcpip/connect`.

## Context

- **Device**: Samsung SM-S928B (S24 Ultra, Android 16), conectado vía ADB.
- **Entorno**: Garuda Linux (Broadwing), Hyprland 0.56.2 (Wayland), locale `es_MX.UTF-8`.
- **Decisión**: la web actual es **legacy** y no se ejecuta; se instala la app nativa.
- **ID de app**: `com.gekko.adb` (desktop entry e ícono con el mismo nombre).
- **Nota**: la instalación en Solus es para un amigo; usar `eopkg` con los
  paquetes `libgtk-3`/`libgtk-4` (Solus no tiene metapaquetes `gtk3`/`gtk4`).

## Architecture

- **Núcleo headless** (`gekko_adb_core.py`): sin `gi` → testable sin display, usado
  igual por GTK3 y GTK4. Env overrides para tests:
  `GEKKO_ADB_BASE` (dir del catálogo), `GEKKO_ADB_EXECUTABLE` (adb fake),
  `GEKKO_SCRCPY_EXECUTABLE`, `GEKKO_PROJECT_DIR`.
- **Tema** (`gekko_adb_theme.py`): Matugen si existe, si no fallback system/dark/light;
  monitoriza el archivo de config del tema y recarga en vivo.
- **Frontends**: GTK4 (`gekko-adb-gtk4.py`) y GTK3 (`gekko-adb-gtk3.py`) — APIs
  específicas por toolkit (append vs add, etc.). No cargar ambos toolkits en el
  mismo proceso.
- **Instalación** (`install.sh`): XDG_DATA_HOME/XDG_STATE_HOME/XDG_CONFIG_HOME, nunca
  root, nunca rutas de usuario hardcodeadas. Detecta la distro vía `/etc/os-release`
  (`arch`/`garuda` → pacman, `solus` → eopkg). El launcher `~/.local/bin/gekko-adb`
  apunta a la instalación (no al checkout) y exporta `GEKKO_ADB_PROJECT_DIR`.

## Coding Notes

- `CommandWorker` contract: exactly one terminal callback — `on_done(result)` for any
  result (success True/False), `on_error(err)` only if the thread aborted by exception.
- Los callbacks del worker no se llaman desde el hilo de la UI; aplicar con
  `GLib.idle_add`.
- Comandos ADB lentos (scrcpy, logcat, boot) NO bloquear: usar `start_command` /
  `Gio.Subprocess` async o `CommandWorker`.
- No comentarios decorativos en el código; texto de UI en español (locale es_MX).
- `adb devices -l` separa con espacios (no tabs); parsear `parts[1] == 'device'`.
- GTK4 pygobject NO soporta `GObject.set_data/get_data` (usar atributos Python
  `widget.nombre = valor`). GTK3 `Label.set_wrap` no existe → `set_line_wrap`.
- GTK4: selector de archivos solo con `Gtk.FileDialog` async (sin `run()`, que
  está bloqueado en el hilo de la UI); GTK3: `Gtk.FileChooserDialog.run()`.
- En el proceso de tests GTK3 y GTK4 no coexisten: `discover` cubre core/tema/GTK3,
  y `test_ui_gtk4` se ejecuta por separado.
