<div align="center">

<img src="assets/gekko-adb.png" width="160" alt="Gekko ADB Studio">

# 🦎 Gekko ADB Studio

**Master Suite de control ADB para Linux** · nativa GTK · tema **Matugen** dinámico

*Creado por [The-Gekko](https://github.com/The-Gekko)*

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
| 🧹 **Presets de debloat** | Samsung, Xiaomi/HyperOS, MIUI y Google con un clic |
| 👑 **Roles de sistema** | Launcher, SMS, teléfono y asistente por defecto |
| 📦 **Instalación y transferencia** | APK, archivos y scripts de un vistazo |
| 🔌 **USB / Wi-Fi** | Gestión completa del servidor ADB |
| 📱 **scrcpy** | Espejo y control del dispositivo integrados |

---

## 🚀 Instalación

### Arch / Garuda

```bash
git clone https://github.com/The-Gekko/gekko-adb.git
cd gekko-adb
./install.sh          # instala dependencias + app
gekko-adb             # lanza la app
```

### Solus

```bash
git clone https://github.com/The-Gekko/gekko-adb.git
cd gekko-adb
./install.sh          # detecta eopkg y usa libgtk-3/libgtk-4
gekko-adb
```

> El instalador respeta los estándares XDG, nunca corre como root y crea
> el launcher `gekko-adb`, el desktop entry `com.gekko.adb` y el ícono hicolor.

---

## 🛠️ Uso

```bash
gekko-adb                     # abrir la app instalada
./bin/gekko-adb               # abrir desde el checkout (dev)
./install.sh --check          # diagnóstico sin escribir nada
./install.sh --uninstall      # desinstalar (conserva config y logs)
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
python3 -m unittest discover -s . -p 'test_*.py'   # core + tema + GTK3
python3 -m unittest test_ui_gtk4 -v                # GTK4 (proceso aparte)
```

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
| `android-tools` | Comandos ADB (`adb` + driver USB) |
| `scrcpy` | Espejo y control de pantalla del teléfono |
| `glib2` | Librerías base del entorno GTK |
| `xdg-utils` | Integración con el escritorio |
| `matugen` *(opcional)* | Tema dinámico sincronizado con tu wallpaper |

Instalación manual (Arch/Garuda):

```bash
sudo pacman -S --needed python python-gobject gtk3 gtk4 android-tools scrcpy glib2 xdg-utils
sudo pacman -S matugen   # opcional
```

Instalación manual (Solus):

```bash
sudo eopkg install python python-gobject libgtk-3 libgtk-4 android-tools scrcpy glib2 xdg-utils
```

> Si `matugen` no está instalado, la app usa un tema de respaldo
> (system/dark/light) sin problemas.

### 📱 En tu teléfono (Android)

1. Abre **Ajustes → Acerca del teléfono** y toca **"Número de compilación"** 7 veces
   para habilitar las **Opciones de desarrollador**.
2. En **Ajustes → Opciones de desarrollador**, activa **"Depuración por USB"**.
3. Conecta el teléfono por USB y acepta el diálogo **"¿Permitir depuración USB?"**.

> Para **Wi-Fi**: en la app usa la opción del servidor ADB (`adb tcpip` + conexión
> por IP), o desde la terminal:
>
> ```bash
> adb devices                 # verifica que aparece tu equipo
> adb tcpip 5555              # activa ADB por red
> adb connect <ip-del-teléfono>:5555
> ```
>
> Si tu dispositivo no se detecta, revisa que existan las reglas **udev** de Android
> (las instala `android-tools`) y reconecta el cable.

---

<div align="center">

**Hecho con 💚 por [The-Gekko](https://github.com/The-Gekko)**

*Gekko ADB Studio — ADB hecho simple y bonito*

</div>
