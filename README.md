# Statoris Sync — Precision Local & Remote Synchronization Engine

Aplicación corporativa nativa para Windows desarrollada bajo el sistema de diseño **Statoris (Executive Light & Dark Titanium)** para la sincronización inteligente de archivos y directorios locales y remotos.

---

## 🌟 Características Principales

1. **Sincronización Multi-Directorio (`Dir 1 ↔ Dir 1 Remoto`, `Dir 2 ↔ Dir 2 Remoto`, ...)**:
   - Cada tarea permite añadir **1 o múltiples pares de directorios** simultáneos (`+ Añadir Par de Directorios`).
   - Además, el panel lateral izquierdo permite gestionar múltiples tareas/perfiles independientes y ejecutarlas individualmente o todas a la vez (`⚡ Sincronizar Todas las Tareas`).

2. **Sincronización Local y Remota Multi-Protocolo**:
   - **LOCAL / SMB**: Copia directa de alta velocidad en discos locales, unidades USB externas o recursos compartidos en red (`\\servidor\carpeta`).
   - **SSH / SFTP**: Transferencia cifrada por túnel SSH (soporta autenticación por contraseña o clave privada `.pem` / `id_rsa`).
   - **SCP**: Transferencia nativa mediante protocolo SCP sobre SSH con preservación de marcas de tiempo.
   - **FTP / FTPS**: Soporte para servidores FTP estándar y FTPS (TLS/SSL explícito) con modo pasivo (`PASV`).
   - **Explorador Visual Remoto**: Incluye ventana interactiva (`🌐 Configurar / Explorar Remoto`) con botón **`🔌 Probar Conexión`** y navegación por las carpetas del servidor remoto.

3. **Direccional y Bidireccional**:
   - **`⇄ Bidireccional (Ambos sentidos)`**: Propaga cambios nuevos y modificados en ambas direcciones, detecta conflictos (`⚡`) y propaga eliminaciones de forma inteligente.
   - **`→ Unidireccional (Origen → Destino)`**: Replica de izquierda a derecha (con opción de Modo Espejo).
   - **`← Unidireccional (Destino ← Origen)`**: Replica de derecha a izquierda.

4. **Modos de Copia: Completa, Incremental y Diferencial**:
   - **Completa (`Full`)**: Sincroniza la totalidad de los archivos y registra una nueva *Línea Base Completa*.
   - **Incremental (`Incremental`)**: Transfiere únicamente los archivos creados o modificados desde la **última sincronización (de cualquier tipo)**.
   - **Diferencial (`Differential`)**: Transfiere todos los archivos creados o modificados desde la **última sincronización Completa**, sin sobrescribir la línea base completa.

5. **Sincronización Activa en Tiempo Real (`Watchdog`)**:
   - Detecta instantáneamente cualquier creación, modificación, movimiento o borrado de archivos en los directorios vigilados y dispara la sincronización tras una ventana de estabilización (*debounce* configurable).

6. **Programador de Sincronizaciones**:
   - Programación automática por **intervalo de minutos**, **diariamente a una hora fija**, **semanalmente por días**, o **al iniciar el sistema**, además de integración directa con el **Programador de Tareas de Windows (`schtasks`)**.

7. **Inicio con Windows y Bandeja del Sistema (`IconTray`)**:
   - Interruptor directo **`Iniciar con Windows`** (registro automático en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
   - Minimizado silencioso a la bandeja del sistema de Windows (**System Tray / IconTray**) con menú rápido (Abrir, Sincronizar Todo, Activar Inicio con Windows, Salir).

---

## 🚀 Ejecución

Haz doble clic directamente sobre el ejecutable autónomo:
- **`Statoris_Sync.exe`**

O ejecuta desde código fuente con Python:
```powershell
python main_window.py
```
