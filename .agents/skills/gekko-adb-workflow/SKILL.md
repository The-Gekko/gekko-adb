---
name: gekko-adb-workflow
description: Flujo de trabajo automatizado para Gekko ADB con auditoría previa, consulta de fuentes oficiales (Garuda, Arch, Solus), delegación obligatoria al modelo local Jan y guardrail de subida a GitHub.
---

# Gekko ADB Workflow

Este workflow estandariza y automatiza el desarrollo del proyecto **Gekko ADB** (`/home/thegekko/Documentos/google Studio/Gekko ADB`).

## Secuencia Ejecutiva

1. **Auditoría Previa Obligatoria**:
   - Inspeccionar los archivos de código relevantes (`gekko_adb_core.py`, `gekko-adb-gtk4.py`, `gekko-adb-gtk3.py`, `install.sh`, etc.).
   - Ejecutar la suite de tests para asegurar estabilidad inicial:
     ```bash
     python3 -m unittest discover -s . -p 'test_*.py'
     python3 -m unittest test_ui_gtk4 -v
     ```

2. **Consulta a Fuentes Oficiales**:
   - Guiarse e investigar siempre en la documentación y foros oficiales si se trata de paquetes, GTK, ADB o comportamiento en distros:
     - **Solus**: https://getsol.us | https://discuss.getsol.us | https://getsol.us/blog/
     - **Garuda**: https://wiki.garudalinux.org/en/home | https://forum.garudalinux.org
     - **Arch**: https://archlinux.org/packages/ | https://bbs.archlinux.org | https://wiki.archlinux.org/title/Main_page | https://gitlab.archlinux.org/archlinux | https://security.archlinux.org | https://aur.archlinux.org

3. **Co-Orquestación con Modelo Local (Jan)**:
   - Inmediatamente después de la auditoría, enviar el resumen de la auditoría y el plan propuesto al servidor local de Jan:
     ```bash
     python ~/.gemini/config/plugins/local-orchestration/skills/jan-delegator/query_jan.py "Auditoría realizada en Gekko ADB: <hallazgos>. Plan propuesto: <propuesta>. Por favor analiza y valida este plan."
     ```

4. **Implementación y Verificación de Pruebas**:
   - Aplicar los cambios necesarios en la base de código.
   - Re-ejecutar los tests unitarios para verificar que no haya regresiones.

5. **Guardrail de Subida a GitHub**:
   - Ruta local del repositorio: `/home/thegekko/Documentos/google Studio/Gekko ADB`
   - **SOLO** ejecutar `git push` o subir cambios a GitHub cuando el usuario lo pida de forma explícita.
   - **EXCLUSIÓN OBLIGATORIA**: El archivo `AGENTS.md` **NUNCA** debe incluirse en el push a GitHub. Asegurarse de que esté excluido o desmarcado (`git restore --staged AGENTS.md`) antes de subir.


6. **Refinamiento Continuo de Delegaciones**:
   - Conforme se avance en el desarrollo, actualizar y reescribir este workflow y las respuestas para aumentar el nivel de automatización en la delegación.

7. **Herramientas de Alto Rendimiento para Refactorización Masiva**:
   - Para tareas de búsqueda masiva o refactorización AST en el proyecto, preferir `ast-grep` (`sg`), `ripgrep` (`rg`) y `fd` en lugar de regex/Python mono-hilo:
     ```bash
     sg --pattern 'import $A' --lang python   # Análisis sintáctico preciso por AST
     rg "patron_busqueda"                      # Búsqueda multihilo ultra-rápida
     ```

