<div align="center">

<img src="assets/gekko-adb.png" width="160" alt="Gekko ADB Studio">

# 🦎 Gekko ADB Studio

**Master Suite de control ADB para Linux** · nativa GTK · tema **Matugen** dinámico

*Creado por [The-Gekko](https://github.com/The-Gekko)*
*Imagen del ícono generada por IA — Google Gemini (Nano Banana)*

![Linux](https://img.shields.io/badge/Linux-Garuda%2FArch%2FSolus-0ea5e9?style=flat-square&logo=linux&logoColor=white)
![GTK](https://img.shields.io/badge/GTK-3%20%2F%204-4ea5d4?style=flat-square&logo=gtk&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square&logo=python&logoColor=white)
![ADB](https://img.shields.io/badge/Android-ADB-3ddc84?style=flat-square&logo=android&logoColor=white)

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
| 🎮 **Control remoto** | Teclas, texto, toques, panel de notificaciones, abrir URL/ajustes, radios (svc) |
| ✅ **Resultados honestos** | Cada botón muestra el comando real y marca error cuando adb falla (conectar, root, scrcpy…) |

---

## 🚀 Instalación

### Instalación rápida (Arch / Garuda / Solus)

Un solo comando — el instalador detecta tu distribución y los paquetes
(`pacman` en Arch/Garuda, `eopkg` en Solus):

```bash
curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh | bash
```

> Al instalar por pipe (`curl … | bash`) la entrada no es interactiva y el
> instalador confirma las dependencias automáticamente (`sudo` te pedirá la
> contraseña igualmente). Si prefieres confirmar paquete a paquete o pasar
> opciones, guarda el script primero:
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh -o /tmp/gekko-install.sh
> bash /tmp/gekko-install.sh            # con prompt interactivo
> bash /tmp/gekko-install.sh --no-deps  # sin tocar el gestor de paquetes
> ```

### Desde el código fuente (desarrollo)

```bash
git clone https://github.com/The-Gekko/gekko-adb.git
cd gekko-adb
./install.sh          # instala dependencias + app
gekko-adb             # lanza la app
```

> El instalador respeta los estándares XDG, nunca corre como root y crea
> el launcher `gekko-adb`, el desktop entry `com.gekko.adb` y el ícono hicolor.
> Si no hay `curl` o `wget`, el instalador descarga las fuentes con Python.

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

> La desinstalación **conserva** tu configuración, logs y presets en
> `~/.config/gekko-adb` y `~/.local/state/gekko-adb/logs`. Elimina el launcher,
> el desktop entry, el ícono y la app instalada. Si quieres borrarlo todo,
> elimina esas carpetas manualmente.

---

## 🛠️ Uso

```bash
gekko-adb                     # abrir la app instalada
./bin/gekko-adb               # abrir desde el checkout (dev)
./install.sh --check          # diagnóstico sin escribir nada
~/.local/share/gekko-adb/app/install.sh --uninstall  # desinstalar
```

---

## 🧱 Arquitectura

```
gekko_adb_core.py      Núcleo headless sin gi (runner ADB, catálogo, debloat, logs)
gekko_adb_theme.py     Tema dinámico Matugen con fallback system/dark/light
gekko-adb-gtk4.py      Frontend GTK 4
gekko-adb-gtk3.py      Frontend GTK 3
adb_commands.json      Catálogo de comandos ADB con campos editables
debloat_presets.json   Presets de desbloqueo por marca
install.sh             Instalador multi-distro (pacman / eopkg)
```

---

## 🧪 Tests

```bash
python3 -m unittest discover -s . -p 'test_*.py'   # core + tema + GTK3 (92 tests)
python3 -m unittest test_ui_gtk4 -v                # GTK4 (proceso aparte; no coexiste con GTK3)
```

Los tests del núcleo usan un `adb` falso que registra el **argv exacto** de
cada llamada: cada botón del catálogo afirma el comando real que se envía a
adb, con uno y con dos dispositivos conectados.

---

## 📦 Dependencias

### 🔧 En tu PC (Linux)

`./install.sh` **instala todo automáticamente** con tu gestor de paquetes.
Esta es la lista en caso de que quieras hacerlo a mano o saber qué necesita:

| Paquete | Para qué sirve |
|---|---|
| `python` | Interpreta la app |
| `python-gobject` | Bindings Python ↔ GTK |
| `gtk3` / `gtk4` (Solus: `libgtk-3` / `libgtk-4`) | Toolkit de interfaz gráfica |
| `android-tools` | Comandos ADB (`adb`) |
| `android-udev` *(Arch)* | Reglas udev para que el teléfono se detecte sin root |
| `scrcpy` | Espejo y control de pantalla del teléfono |
| `glib2` | Librerías base del entorno GTK |
| `xdg-utils` | Integración con el escritorio |
| `xdg-user-dirs` | Detecta `~/Descargas`, `~/Imágenes`… según tu idioma |
| `curl` | Descarga de fuentes en la instalación por un comando |
| `matugen` *(opcional)* | Tema dinámico sincronizado con tu wallpaper |

Instalación manual (Arch/Garuda):

```bash
sudo pacman -S --needed python python-gobject gtk3 gtk4 android-tools android-udev scrcpy glib2 xdg-utils xdg-user-dirs curl
sudo pacman -S matugen   # opcional
```

Instalación manual (Solus; ahí `python` es Python 2, el intérprete es `python3`):

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

<div align="center">

**Hecho con 💚 por [The-Gekko](https://github.com/The-Gekko)**

*Gekko ADB Studio — ADB hecho simple y bonito*

</div>
