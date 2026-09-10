<div align="center">

<img src="assets/gekko-adb-512.png" width="160" alt="Gekko ADB Studio">

# 🦎 Gekko ADB Studio

**Master Suite de control ADB para Linux** · nativa GTK · tema **Matugen** dinámico

*Creado por [The-Gekko](https://github.com/The-Gekko)*
*Imagen del ícono generada por IA — Google Gemini (Nano Banana)*

![Linux](https://img.shields.io/badge/Linux-Garuda%2FArch%2FSolus-0ea5e9?style=flat-square&logo=linux&logoColor=white)
![GTK](https://img.shields.io/badge/GTK-4%20%E2%89%A5%204.12%20%2F%203.24-4ea5d4?style=flat-square&logo=gtk&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?style=flat-square&logo=python&logoColor=white)
![ADB](https://img.shields.io/badge/Android-ADB-3ddc84?style=flat-square&logo=android&logoColor=white)
![Licencia](https://img.shields.io/badge/Licencia-zlib%2Flibpng-yellow?style=flat-square)

</div>

---

## ✨ Características

| | |
|---|---|
| 🖥️ **Interfaz nativa GTK** | Frontends GTK 4 y GTK 3 desde un mismo núcleo headless |
| 🎨 **Tema Matugen dinámico** | El color del sistema, sincronizado con tu wallpaper en vivo |
| 📊 **Dashboard multi-marca** | Samsung (Knox), Xiaomi / Redmi / Poco (Bootloader + Verified) y genéricos (SELinux) |
| 🧹 **Presets de debloat** | Samsung, Xiaomi/HyperOS, MIUI y Google con un clic, cada uno con su botón **Restaurar** |
| 👑 **Roles de sistema** | Launcher, SMS, teléfono y asistente por defecto |
| 📦 **Instalación y transferencia** | APK, APK divididos (splits), varias apps a la vez, archivos y carpetas |
| 🔌 **USB / Wi-Fi** | Servidor ADB, emparejamiento inalámbrico (`adb pair`), IP del teléfono, reconexión |
| 📱 **scrcpy y screenrecord** | Espejo, grabación y captura de pantalla |
| 🕹️ **Gaming en el PC** | Los juegos del móvil en el monitor, con **teclado, ratón y mando reales** (`uhid`/`aoa`), pantalla virtual a resolución de PC y modo de latencia mínima |
| ⚡ **Rendimiento y juegos** | Modo de juego de Android (`cmd game`), tasa de refresco forzada, estado térmico, fotogramas/jank y recompilación (dexopt) |
| 🔧 **Ajustes finos del sistema** | Permisos `appops`, brillo por porcentaje, Ahorro de datos (`netpolicy`), Doze y consumo por app |
| 🎮 **Control remoto** | Teclas, texto, toques, panel de notificaciones, abrir URL/ajustes, radios (svc) |
| ✅ **Resultados honestos** | Cada botón muestra el comando real y marca error cuando adb falla (conectar, root, scrcpy…) |

---

## 🚀 Instalación

Hay **exactamente dos formas** de instalar Gekko ADB Studio: **por curl** o
**clonando el repositorio**. Las dos ejecutan el mismo `install.sh`, escriben
las mismas rutas y se desinstalan igual. No hay releases: la app se instala
siempre desde la rama `main` de este repositorio.

> ⚠️ **Elige una sola vía.** Como las dos escriben las mismas rutas, la última
> que ejecutes gana; para cambiar de vía, desinstala primero con la misma con la
> que instalaste.

### 📋 Requisitos

- **Python 3.8+** (el código no usa nada posterior a 3.7) y `python-gobject`.
- **GTK 4 ≥ 4.12** para el frontend GTK 4 (usa `Gtk.FileDialog` y
  `CssProvider.load_from_string`) **o GTK 3.24** para el frontend GTK 3.
  El launcher elige GTK 4 si está disponible y, si no, GTK 3.
- `adb` (`android-tools`). `scrcpy` para espejo, grabación y la sección
  **Gaming** (ver más abajo: el mando pide scrcpy 3.1+ y la pantalla virtual 3.0+).

En las dos vías el instalador detecta tu distribución por `/etc/os-release` y
usa su gestor de paquetes:

| Distribución | Gestor |
|---|---|
| Arch, Garuda, Manjaro, EndeavourOS, CachyOS y cualquiera con `ID_LIKE=arch` | `pacman` |
| Solus | `eopkg` |
| No reconocida | Si existe `pacman` se asume Arch; si existe `eopkg`, Solus; si no hay ninguno, el instalador **se detiene con un error** y te pide instalar las dependencias a mano y volver a ejecutar con `--no-deps` |

### ⚡ Por curl

Un solo comando, sin descargar nada más a mano: el script se baja el código de
la rama `main` (modo standalone) y lo instala.

```bash
curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh | bash
```

> Al instalar por pipe (`curl … | bash`) la entrada no es interactiva y, si
> faltan paquetes, el instalador los confirma automáticamente (`sudo` te pedirá
> la contraseña igualmente). Si prefieres confirmar paquete a paquete o pasar
> opciones, guarda el script primero:
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh -o /tmp/gekko-install.sh
> bash /tmp/gekko-install.sh            # con prompt interactivo
> bash /tmp/gekko-install.sh --no-deps  # sin tocar el gestor de paquetes
> ```

### 🧑‍💻 Clonando el repositorio

```bash
git clone https://github.com/The-Gekko/gekko-adb.git
cd gekko-adb
./install.sh          # instala dependencias + app
gekko-adb             # lanza la app
```

### ⚙️ Opciones del instalador

| Opción | Efecto |
|---|---|
| `--check` | Diagnóstico sin escribir ni borrar nada (paquetes, launcher, PATH). Incompatible con `--uninstall`: la combinación se rechaza con error |
| `--uninstall` | Elimina la app conservando configuración y logs (ver la sección **Desinstalación**) |
| `--no-deps` | No toca el gestor de paquetes ni recarga udev; solo instala la app |
| `--assume-yes` | Confirma la instalación de dependencias sin preguntar (se asume solo cuando no hay TTY *y* faltan paquetes) |
| `--help`, `-h` | Ayuda, con la distribución detectada y la lista de paquetes |

Variable útil: `GEKKO_ADB_TARBALL` (URL o `file://`) cambia de dónde se
descargan las fuentes en modo standalone (`curl | bash`); si no hay `curl` ni
`wget`, descarga con Python.

### 📂 Qué crea la instalación

El instalador respeta los estándares XDG y **nunca corre como root**:

| Ruta | Contenido |
|---|---|
| `~/.local/bin/gekko-adb` | Launcher (exporta `GEKKO_ADB_PROJECT_DIR` y llama a la app instalada) |
| `~/.local/share/gekko-adb/app/` | La app: núcleo, tema, frontends GTK 3/4, catálogo, presets, `bin/gekko-adb`, `assets/gekko-adb-512.png`, el `LICENSE` y una copia de `install.sh` |
| `~/.local/share/gekko-adb/app.bak.<timestamp>/` | Backup de la versión anterior al reinstalar (se conserva solo el último) |
| `~/.local/share/applications/com.gekko.adb.desktop` | Desktop entry (`Categories=Development;Debugger;`) |
| `~/.local/share/icons/hicolor/512x512/apps/gekko-adb.png` | Ícono hicolor |
| `~/.local/share/metainfo/com.gekko.adb.metainfo.xml` | Metainfo AppStream |
| `~/.config/gekko-adb/config.ini` | Configuración (tema y registro); la crea la app al guardar ajustes |
| `~/.local/state/gekko-adb/logs/` | Directorio de logs (se crea en toda instalación); `gekko-adb.log` (rotado a 1 MB) se escribe cuando activas el registro en la app y también para errores al leer/guardar `config.ini` |

En Arch, si existe `/usr/lib/udev/rules.d/51-android.rules` e instaló
dependencias, intenta recargar udev sin pedir contraseña (`sudo -n`); si `sudo`
no tiene credencial cacheada, muestra el comando para hacerlo a mano
(`sudo udevadm control --reload-rules && sudo udevadm trigger`). Con `--no-deps`
no lo intenta; por eso GekkoApp lo hace él mismo, con `sudo`, tras llamar a
`install.sh --no-deps`.
Si aún existe el desktop entry legacy `GekkoADB.desktop`, se elimina.

> ⚠️ **`~/.local/bin` debe estar en tu `PATH`** para que `gekko-adb` se
> encuentre desde la terminal. El instalador lo comprueba (también con
> `--check`) y, si falta, te muestra la línea a añadir:
>
> ```bash
> export PATH="$HOME/.local/bin:$PATH"   # ~/.bashrc o ~/.zshrc (fish: fish_add_path ~/.local/bin)
> ```
>
> El menú de aplicaciones no lo necesita: el desktop entry usa la ruta completa.

---

## 🧩 Nota: Gekko ADB dentro de GekkoApp (vía conjunta)

[GekkoApp](https://github.com/The-Gekko/GekkoApp) es el Control Center de la
familia Gekko (Rust + Tauri) y puede instalar y desinstalar Gekko ADB Studio
junto al resto de módulos. **No es una tercera forma de instalar este
proyecto**: por dentro instala los paquetes del sistema, clona
`The-Gekko/gekko-adb` (rama `main`, HEAD por HTTPS) en
`~/.cache/gekkoapp/gekko-adb` y ejecuta el `install.sh --no-deps --assume-yes`
de ese clon, así que la app queda en las mismas rutas que con las dos vías de
arriba (en Arch recarga además las reglas udev de `android-udev`, que con
`--no-deps` el instalador no toca). Su desinstalación borra lo mismo que
`install.sh --uninstall` —más los desktop entries legacy y el clon en caché— y
también **conserva** `~/.config/gekko-adb` y `~/.local/state/gekko-adb/logs`.
Los pasos están en el README de GekkoApp.

---

## 🗑️ Desinstalación

La app guarda una copia del instalador en su carpeta, así puedes desinstalar
sin necesidad de tener el código fuente:

```bash
~/.local/share/gekko-adb/app/install.sh --uninstall
```

O por curl, sin descargar nada más:

```bash
curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh -o /tmp/gekko-uninstall.sh
bash /tmp/gekko-uninstall.sh --uninstall
```

Elimina: el launcher `~/.local/bin/gekko-adb`, el desktop entry
`com.gekko.adb.desktop` (y el legacy `GekkoADB.desktop` si aún existe), el
ícono hicolor, el metainfo AppStream,
`~/.local/share/gekko-adb/app`, los backups `app.bak.*` y el `.env` que dejaban
instalaciones anteriores (si la carpeta `~/.local/share/gekko-adb` queda vacía,
también se elimina).

> La desinstalación **conserva** tu configuración en `~/.config/gekko-adb` y
> los logs en `~/.local/state/gekko-adb/logs`. Los presets de debloat viven
> dentro de la app (`debloat_presets.json`) y se van con ella. Si quieres
> borrarlo todo, elimina esas dos carpetas manualmente. Nunca pide `sudo` ni
> toca paquetes del sistema.

---

## 🛠️ Uso

```bash
gekko-adb                     # abrir la app instalada (GTK 4 si está disponible, si no GTK 3)
./bin/gekko-adb               # abrir desde el checkout (dev)
gekko-adb --diagnostics       # adb, scrcpy, GTK y dispositivos, sin abrir la app
./install.sh --check          # diagnóstico del instalador sin escribir nada
```

### Opciones del launcher (`bin/gekko-adb`)

| Opción | Efecto |
|---|---|
| `--gtk4` | Forzar el frontend GTK 4 |
| `--gtk3` | Forzar el frontend GTK 3 |
| `--print-backend` | Imprime `gtk4` o `gtk3` (el que se usaría) y sale, sin abrir la app |
| `--diagnostics` | CLI sin GTK: ruta y versión de `adb`, `scrcpy`, GTK 3/4 disponibles y dispositivos; rc 1 si falta adb o GTK |
| `--json` | CLI sin GTK: estado de conexión y dispositivo en JSON |
| `--version` | `Gekko ADB Studio 2.1.0` |
| `--help`, `-h` | Ayuda |

### Variables de entorno

| Variable | Efecto |
|---|---|
| `GEKKO_ADB_GTK=auto\|gtk3\|gtk4` | Frontend por defecto (`auto`: GTK 4 y, si no, GTK 3) |
| `GEKKO_ADB_PYTHON` | Intérprete a usar (por defecto `python3`) |
| `GEKKO_ADB_PROJECT_DIR` | Carpeta con el código (el launcher instalado la exporta a `~/.local/share/gekko-adb/app`) |

---

## 🕹️ Gaming: jugar en el PC con los juegos del móvil

La categoría **Gaming (jugar en la PC)** convierte el teléfono en una consola:
la pantalla se ve en el monitor y se juega con el **teclado, el ratón y el
mando que ya tienes en el PC**, sin apps intermedias y sin root. El botón
principal reproduce exactamente este comando:

```bash
scrcpy -m 1080 -b 9M --video-codec=h264 --keyboard=uhid --mouse=uhid
```

Con `--keyboard=uhid` y `--mouse=uhid` el móvil ve un teclado y un ratón
**físicos**, no toques simulados: el puntero queda **capturado** en modo
relativo, que es justo lo que hace jugable un shooter. Para devolver el ratón
al escritorio, pulsa **LAlt**, **LSuper** o **RSuper** (vuelve a pulsar para
capturarlo otra vez).

| Botón | Banderas que lanza | Requiere |
|---|---|---|
| 🎮 **Modo Gaming (teclado y ratón)** | `-m 1080 -b 9M --video-codec=h264 --keyboard=uhid --mouse=uhid` | scrcpy 2.7+ |
| 🕹️ **Gaming con mando** | Lo mismo + `--gamepad=uhid` (o `aoa` si el móvil va por USB y `uhid` falla) | scrcpy 3.1+ |
| 🖥️ **Juego en pantalla virtual** | `-b 9M --video-codec=h264 --new-display=1920x1080 --start-app=<paquete> --keyboard=uhid --mouse=uhid` | scrcpy 3.0+ y **Android 14+** |
| ⚡ **Latencia mínima (juegos de reflejos)** | `-m 720 -b 4M --video-codec=h264 --max-fps=60 --video-buffer=0 --no-audio --keyboard=uhid --mouse=uhid` | scrcpy 3.0+ (`--video-buffer`) |
| 🔌 **Modo OTG (solo controles)** | `--otg --keyboard=aoa --mouse=aoa --gamepad=aoa`: el PC hace de teclado, ratón y mando por el cable, **sin vídeo y sin depuración ADB** | Solo USB; el mando, scrcpy 3.1+ |
| 🧾 **Listar codificadores** | `--list-encoders`, con la salida dentro de la app | — |
| 📋 **Listar apps del móvil** | `--list-apps`: los nombres de paquete que pide `--start-app` | scrcpy 3.0+ |
| ⌨️ **Configurar teclado físico** | `adb shell am start -a android.settings.HARD_KEYBOARD_SETTINGS` | — |

Todos los campos son editables (resolución, bitrate, códec, FPS, codificador,
pantalla completa, apagar la pantalla del móvil…) y **un campo opcional vacío
no genera bandera**: si dejas *Codificador* en blanco, el comando sale sin
`--video-encoder` y lo elige scrcpy. La pantalla virtual admite
`1920x1080`, `1920x1080/420` (con dpi) o vacío para copiar la pantalla real, y
en *App a lanzar* el prefijo `?` busca por nombre aproximado (`?genshin`) y `+`
fuerza detener la app antes (`+?genshin`).

> ⚠️ **Configura el teclado físico UNA vez o las teclas saldrán cambiadas.**
> Con `uhid`/`aoa` la distribución la decide el teléfono, no el PC: si no lo
> haces, WASD y compañía llegan movidos. Pulsa **Configurar teclado físico**,
> que abre en el teléfono *Ajustes → Sistema → Idiomas e introducción →
> Teclado físico*, y elige ahí tu distribución. Se hace una sola vez por
> dispositivo.

> ⚠️ **El codificador del comando de ejemplo es el del móvil del autor.**
> El comando original de esta sección llevaba
> `--video-encoder=c2.android.avc.encoder`, que **no existe en todos los
> teléfonos**: por eso el campo *Codificador* viene **vacío** por defecto. Pulsa
> **Listar codificadores** para ver los de tu móvil y copia el nombre exacto en
> ese campo, o déjalo en blanco y deja que scrcpy elija.

---

## ⚡ Rendimiento y juegos

La categoría **Rendimiento y Juegos** es la otra mitad de *Gaming*: **Gaming
juega desde el PC** (scrcpy pone la pantalla en el monitor), **Rendimiento toca
el móvil** para que el juego vaya mejor en su propia pantalla. Son los ajustes
que Android esconde en `cmd game`, `settings`, `dumpsys` y el compilador de
apps, sin root y sin instalar nada en el teléfono:

```bash
adb shell cmd game mode performance com.miHoYo.GenshinImpact
adb shell settings put system min_refresh_rate 120
adb shell settings put system peak_refresh_rate 120
```

| Botón | Comando real | Requiere |
|---|---|---|
| 🎮 **Modo de juego de Android** | `cmd game mode <standard\|performance\|battery> <paquete>` | **Android 12+** y que la app sea un juego (ver aviso) |
| 📋 **Modos de juego disponibles** | `cmd game list-modes <paquete>`: qué modos admite ese juego y cuál tiene puesto | Android 12+ y app de tipo juego |
| 🔍 **Ajustes finos del juego (actuales)** | `cmd game list-configs <paquete>`: el reescalado y los FPS aplicados | Android 12+ y app de tipo juego |
| 🎚️ **Ajuste fino del juego (reescalado y FPS)** | `cmd game set --downscale <0.3…0.9\|disable> --fps <n> <paquete>` | Android 12+ y app de tipo juego |
| ↩️ **Restablecer el modo de juego** | `cmd game reset <paquete>`: deshace modo y ajustes finos | Android 12+ y app de tipo juego |
| 👁️ **Ver la tasa de refresco fijada** | `settings get system min_refresh_rate` y `peak_refresh_rate` | — |
| ⏱️ **Forzar tasa de refresco** | `settings put system min_refresh_rate <Hz>` **y** `peak_refresh_rate <Hz>`, las dos claves a la vez | Un modo que tu pantalla admita de verdad |
| ♻️ **Restablecer la tasa de refresco** | `settings delete system min_refresh_rate` y `peak_refresh_rate` (ver aviso) | — |
| 📈 **Fotogramas y tirones de una app** | `dumpsys gfxinfo <paquete>`: fotogramas, jank y percentiles 50/90/95/99 | La app abierta y usada un rato antes de pulsar |
| 🌡️ **Estado térmico** | `dumpsys thermalservice`: `Thermal Status: 0` es *sin limitar*; cuanto más sube, más frena el móvil | — |
| 🛠️ **Recompilar app (dexopt)** | `cmd package compile -m <speed\|speed-profile\|verify> -f <paquete>` | Paciencia: minutos (ver aviso) |
| 🧹 **Deshacer la recompilación** | `cmd package compile --reset <paquete>`: deja la app como recién instalada | — |

Las dos claves de refresco van **siempre en pareja**: fijar solo el pico deja
que el móvil siga bajando la tasa cuando quiera. En *Ajuste fino del juego* los
dos campos son opcionales y, como en Gaming, **un campo vacío no genera
bandera**: con el reescalado vacío sale solo `--fps`, con los FPS vacíos solo
`--downscale`, y con los dos vacíos el botón ni siquiera llama a adb (responde
*«Indica al menos un ajuste: reescalado o FPS»*).

> ⚠️ **`cmd game` solo funciona con apps declaradas como juego.** Los cinco
> botones de modo de juego necesitan que la app lleve
> `android:appCategory="game"` en su manifiesto. Con cualquier otra, el móvil
> responde literalmente:
>
> ```
> Package com.ejemplo.app is not of game type, to use the game mode commands, it must specify game category in the manifest as android:appCategory="game"
> ```
>
> …y, peor, **sale con código 0**: para adb el comando "funcionó". Gekko ADB lee
> esa salida y marca el botón como **error** a propósito, para que no parezca
> que sí ha cambiado algo. No es un fallo de la app ni de tu móvil: esa app no
> es un juego para Android.

> ⚠️ **La tasa de refresco se restablece BORRANDO las claves, no poniendo un
> número.** Sin nada forzado, `settings get system min_refresh_rate` responde
> `null`: el valor de fábrica es *«sin fijar»*, así que solo
> `settings delete` lo devuelve a eso. Escribir "60" a mano dejaría clavada una
> tasa que no tiene por qué ser la de tu pantalla. Por eso hay un botón
> **Restablecer la tasa de refresco** aparte: después de pulsarlo, *Ver la tasa*
> debe volver a responder `null`.

> ⚠️ **Recompilar una app tarda minutos y `batterystats` llena el panel.**
> `cmd package compile` es dexopt de verdad: en un juego grande son minutos con
> el móvil al máximo (el núcleo le da **900 s** de margen antes de cortar), así
> que no lo lances con poca batería ni desconectes el cable mientras trabaja.
> Y *Consumo por app (batterystats)*, en **Diagnóstico y Logs**, escupe **miles
> de líneas**: si solo quieres guardarlas, usa *Generar bugreport*.

### 🔧 Ajustes finos repartidos por otras categorías

Junto a la categoría nueva, estos botones se sumaron a categorías que ya
existían, porque es donde se buscan:

| Botón | Categoría | Comando real |
|---|---|---|
| 🩺 **Doze y ahorro de energía** | Diagnóstico y Logs | `dumpsys deviceidle`: fase de Doze, cuánto falta para la siguiente y apps exentas |
| 🔋 **Consumo por app (batterystats)** | Diagnóstico y Logs | `dumpsys batterystats`: quién gasta batería desde la última carga completa |
| ⏳ **Tiempo encendido y carga** | Diagnóstico y Logs | `uptime`: tiempo desde el arranque y carga media de 1, 5 y 15 min |
| 📡 **Servicios del sistema** | Diagnóstico y Logs | `service list`: los servicios vivos, o sea qué `dumpsys` existen en **tu** móvil |
| 👥 **Usuarios y perfiles** | Gestor de Paquetes | `pm list users`: el id de cada usuario (el `0` es el que usan el debloat y *Desinstalar (usuario 0)*) |
| 🔎 **Ver permisos finos (appops)** | Gestor de Paquetes | `cmd appops get <paquete> [operación]`: el modo real (allow/ignore/deny/foreground), mucho más de lo que ve `pm grant` |
| 🔐 **Cambiar permiso fino (appops)** | Gestor de Paquetes | `cmd appops set <paquete> <operación> <allow\|ignore\|deny\|default>`: `SYSTEM_ALERT_WINDOW`, `GET_USAGE_STATS`, `RUN_IN_BACKGROUND`… |
| 🔓 **Quitar la pantalla de bloqueo** | Control Remoto e Input | `wm dismiss-keyguard`: retira la pantalla de bloqueo (**no** salta PIN, patrón ni huella: con bloqueo seguro deja el móvil pidiendo el código) |
| 📶 **Datos en segundo plano: consultar** | Radios y Energía | `cmd netpolicy get restrict-background` / `list restrict-background-blacklist\|whitelist` / `list wifi-networks` |
| 🚦 **Ahorro de datos: activar o desactivar** | Radios y Energía | `cmd netpolicy set restrict-background <true\|false>`: el interruptor global |
| 🔆 **Ver brillo de pantalla** | Ajustes y Pantalla | `cmd display get-brightness --unit percentage` (sin `--unit` devuelve 0.0-1.0) |
| 🌗 **Cambiar brillo de pantalla** | Ajustes y Pantalla | `cmd display set-brightness <0-100> --unit percentage` |

> ⚠️ **`cmd netpolicy list …` devuelve UID numéricos, no nombres de paquete.**
> Para saber de quién es cada número, crúzalo con *Detalle de un paquete*
> (`dumpsys package`) en **Gestor de Paquetes**. Y los nombres de operación de
> `appops set` se sacan de *Ver permisos finos*: si te inventas uno, el móvil
> responde `Error: Unknown operation string`.

---

## 🎨 Tema Matugen

La app **no ejecuta `matugen`**: solo lee el CSS que Matugen ya generó. Al
elegir el tema *matugen* busca, en este orden, el primer archivo que exista:

1. `~/.config/gekko-adb/matugen.css`
2. `~/.cache/matugen/colors-gtk.css`
3. `~/.config/matugen/generated/gekko-adb.css`

(`~/.config` y `~/.cache` respetan `XDG_CONFIG_HOME` / `XDG_CACHE_HOME`.)
Entiende colores `@define-color` y variables `--nombre` (ignorando bloques
`@media`), decide claro/oscuro por la luminancia del fondo y **vigila el
archivo** con `Gio.FileMonitor` para recargar el tema en vivo cuando Matugen lo
regenera (si aún no existe ninguno, vigila el primero de la lista hasta que
aparezca). Sin CSS, o con un CSS sin colores reconocibles, cae al tema oscuro
y lo indica; los temas `system`, `dark` y `light` funcionan siempre, sin Matugen.

---

## 🧱 Arquitectura

```
bin/gekko-adb          Launcher: elige GTK 4/GTK 3 y pasarela CLI (--diagnostics, --json, --version)
gekko_adb_core.py      Núcleo headless sin gi (runner ADB, catálogo, debloat, logs, CLI)
gekko_adb_theme.py     Tema dinámico Matugen con fallback system/dark/light
gekko-adb-gtk4.py      Frontend GTK 4 (id com.gekko.adb)
gekko-adb-gtk3.py      Frontend GTK 3 (id com.gekko.adb.gtk3)
adb_commands.json      Catálogo de comandos ADB con campos editables
debloat_presets.json   Presets de debloat por marca
install.sh             Instalador multi-distro (pacman / eopkg), XDG, nunca root
assets/                gekko-adb-512.png (ícono instalado) y gekko-adb.png (arte del repo, no se instala)
test_core.py           Tests del núcleo con un adb falso y un scrcpy falso que registran el argv
test_theme.py          Tests del tema y del parser de CSS Matugen
test_ui_gtk3.py        Tests del frontend GTK 3 (necesitan display)
test_ui_gtk4.py        Tests del frontend GTK 4 (necesitan display; proceso aparte)
tests/fixtures/        Salidas reales de dumpsys battery, wm size/density y navigation_mode (AOSP, MIUI, Samsung S24)
```

---

## 🧪 Tests

```bash
python3 -m unittest discover -s . -p 'test_*.py'   # 180 tests: core + tema + GTK 3 (173) y GTK 4 (7, se saltan aquí)
python3 -m unittest test_ui_gtk4                   # 7 tests GTK 4, en su propio proceso
```

GTK 3 y GTK 4 no pueden cargarse en el mismo proceso: `discover` ejecuta 180
tests y termina en `OK (skipped=7)` — 173 de core (159) + tema (9) + GTK 3 (5)
más los 7 de GTK 4, que se saltan en ese proceso— y `test_ui_gtk4` se ejecuta
aparte (7). Los tests de UI usan un display real: sin `DISPLAY` ni
`WAYLAND_DISPLAY` se saltan.

Los tests del núcleo usan un `adb` falso que registra el **argv exacto** de
cada llamada: cada botón del catálogo afirma el comando real que se envía a
adb, con uno y con dos dispositivos conectados. La sección **Gaming** tiene
además un `scrcpy` falso con su propio log de argv, así que cada botón afirma
las banderas exactas que recibiría scrcpy (con el codificador relleno y vacío,
con FPS vacío y con dos dispositivos), sin lanzar scrcpy de verdad. Los botones
de **Rendimiento y juegos** se prueban igual contra el adb falso: el argv de
cada uno, los valores que el móvil debe rechazar, que `settings delete` borra
las dos claves de refresco y que el rechazo de `cmd game` («is not of game
type», con código de salida 0) se marca como error.

---

## 📦 Dependencias

### 🔧 En tu PC (Linux)

`./install.sh` **instala todo automáticamente** con tu gestor de paquetes.
Esta es la lista exacta que instala (`REQUIRED_PACKAGES` en `install.sh`),
por si quieres hacerlo a mano o saber qué necesita:

| Arch / Garuda | Solus | Para qué sirve |
|---|---|---|
| `python` | `python3` | Interpreta la app (Python 3.8+; en Solus `python` es Python 2) |
| `python-gobject` | `python-gobject` | Bindings Python ↔ GTK |
| `gtk3` | `libgtk-3` | Frontend GTK 3 |
| `gtk4` | `libgtk-4` | Frontend GTK 4 |
| `android-tools` | `android-tools` | Comandos ADB (`adb`) |
| `android-udev` | — (no existe en Solus) | Reglas udev para que el teléfono se detecte sin root |
| `scrcpy` | `scrcpy` | Espejo y control de pantalla del teléfono |
| `glib2` | `glib2` | Librerías base del entorno GTK |
| `xdg-utils` | `xdg-utils` | Integración con el escritorio |
| `xdg-user-dirs` | `xdg-user-dirs` | Detecta `~/Descargas`, `~/Imágenes`… según tu idioma (sin él la app usa `$HOME/Descargas` o `$HOME/Downloads` como respaldo) |
| `curl` | `curl` | Solo para la vía por curl / modo standalone (descarga las fuentes); la app no lo usa |
| `matugen` *(opcional)* | — (no está en los repos) | Tema dinámico sincronizado con tu wallpaper |

Instalación manual de las dependencias (Arch/Garuda):

```bash
sudo pacman -S --needed python python-gobject gtk3 gtk4 android-tools android-udev scrcpy glib2 xdg-utils xdg-user-dirs curl
sudo pacman -S matugen   # opcional
```

Instalación manual de las dependencias (Solus; ahí `python` es Python 2, el
intérprete es `python3`):

```bash
sudo eopkg install python3 python-gobject libgtk-3 libgtk-4 android-tools scrcpy glib2 xdg-utils xdg-user-dirs curl
```

> Si `matugen` no está instalado, la app usa un tema de respaldo
> (system/dark/light) sin problemas. En **Solus** `matugen` no está en los
> repos, así que la app usará el tema del sistema (todo lo demás funciona
> igual: los paquetes `libgtk-3`/`libgtk-4`, `android-tools`, `scrcpy` y
> `python-gobject` existen en los repos oficiales).
>
> El adb de `android-tools` en Arch se compila **sin mDNS**: los botones
> "Verificar mDNS" y "Servicios mDNS" solo funcionan con las platform-tools
> de Google. El resto no lo necesita.

### 📱 En tu teléfono (Android)

1. Abre **Ajustes → Acerca del teléfono** y toca **"Número de compilación"** 7 veces
   para habilitar las **Opciones de desarrollador**.
2. En **Ajustes → Opciones de desarrollador**, activa **"Depuración por USB"**.
3. Conecta el teléfono por USB y acepta el diálogo **"¿Permitir depuración USB?"**.

> Para **Wi-Fi** hay dos caminos en la categoría *Conexión Inalámbrica*:
>
> - **Sin cable (Android 11+)**: en el teléfono, *Opciones de desarrollador →
>   Depuración inalámbrica → Vincular dispositivo con código*; en la app pulsa
>   **Emparejar** con esa IP:puerto y el código, y luego **Conectar por IP** con
>   el puerto de depuración inalámbrica.
> - **Con cable la primera vez**: **Activar puerto TCP/IP**, **IP Wi-Fi del
>   celular** y **Conectar por IP**. Desde la terminal sería:
>
> ```bash
> adb devices                 # verifica que aparece tu equipo
> adb tcpip 5555              # activa ADB por red
> adb connect <ip-del-teléfono>:5555
> ```
>
> Si tu dispositivo aparece como *sin permisos USB*, instala las reglas **udev**
> (`android-udev` en Arch) y reconecta el cable; si aparece *sin autorizar*,
> acepta el diálogo en el teléfono.

---

## 📄 Licencia

Este proyecto se distribuye bajo la licencia **zlib/libpng** (SPDX: `Zlib`) —
ver [`LICENSE`](LICENSE). Copyright (c) 2026 The-Gekko.

---

<div align="center">

**Hecho con 💚 por [The-Gekko](https://github.com/The-Gekko)**

*Gekko ADB Studio — ADB hecho simple y bonito*

</div>
