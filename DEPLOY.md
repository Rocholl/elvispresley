# Despliegue en VPS Hetzner — Abuela (descarga Smule)

Guía para levantar el descargador en un servidor Hetzner con Docker Compose, clonando un **repo privado** en un volumen persistente y dejando que el contenedor descargue las canciones solas.

---

## Resumen

| Qué | Detalle |
|-----|---------|
| Objetivo | Descargar ~10.000 grabaciones de Smule (`ElvaTorales1`) |
| Runtime | Python 3 + Playwright (Chromium headless) |
| Persistencia | Volumen Docker `abuela-data` → `/data/repo` (código + `canciones/`) |
| Repo privado | Deploy key SSH o token HTTPS en `.env` |
| Tiempo estimado | Días (cada canción ~30–90 s de navegador + descarga) |
| Disco recomendado | **80–120 GB** (audio + catálogo + margen) |

---

## 1. Crear el VPS en Hetzner

1. [Hetzner Cloud Console](https://console.hetzner.cloud/) → **Add Server**
2. **Ubicación**: Falkenstein o Nuremberg (barato y estable)
3. **Imagen**: Ubuntu 24.04
4. **Tipo**: mínimo **CX32** (4 vCPU, 8 GB RAM) — Playwright consume RAM
5. **Disco**: 80 GB o más. Si el catálogo crece mucho, añade un **Volume** de 100 GB y móntalo en `/data`
6. **SSH key**: la tuya (para entrar al servidor)
7. Crear y anotar la IP pública

### Firewall (recomendado)

Solo necesitas SSH. En Hetzner → Firewalls:

- Entrada: TCP 22 desde tu IP (o 0.0.0.0/0 si no tienes IP fija)
- Nada más abierto

---

## 2. Preparar acceso al repo privado (GitHub)

### Opción A — Deploy key SSH (recomendada)

En tu máquina local:

```bash
ssh-keygen -t ed25519 -f deploy-key -N "" -C "hetzner-abuela"
```

1. Copia `deploy-key.pub` en GitHub → repo **abuela** → Settings → Deploy keys → Add
2. **Solo lectura** (no marques write)
3. Guarda `deploy-key` (privada) para el servidor — **nunca la subas al repo**

### Opción B — Token HTTPS

GitHub → Settings → Developer settings → Fine-grained token:

- Repo: solo `abuela`
- Permisos: Contents → Read

En `.env`:

```env
GIT_REPO_URL=https://x-access-token:ghp_TU_TOKEN@github.com/TU_USUARIO/abuela.git
```

Con HTTPS no hace falta montar `deploy-key`.

---

## 3. Subir el proyecto al repo privado

Asegúrate de que el repo contiene al menos:

```
abuela/
├── descargar.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── .env.example
```

**No subas** `canciones/*.m4a`, `cookies.txt`, `deploy-key` ni `.env`.

Opcional: sube `canciones/catalogo-completo.json` si ya lo tienes — el script lo reutiliza y evita re-listar Smule.

---

## 4. Configurar el servidor

Conéctate:

```bash
ssh root@TU_IP_HETZNER
```

### Instalar Docker

```bash
apt update && apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
```

### Directorio de despliegue

```bash
mkdir -p /opt/abuela && cd /opt/abuela
```

Copia desde tu máquina (solo lo necesario para construir la imagen):

```bash
scp Dockerfile docker-compose.yml entrypoint.sh requirements.txt .env.example root@TU_IP:/opt/abuela/
scp deploy-key root@TU_IP:/opt/abuela/deploy-key
chmod 600 /opt/abuela/deploy-key   # en el servidor
```

### Variables de entorno

```bash
cp .env.example .env
nano .env
```

Ejemplo con SSH:

```env
GIT_REPO_URL=git@github.com:TU_USUARIO/abuela.git
SMULE_USER=ElvaTorales1
DEPLOY_KEY_PATH=./deploy-key
```

---

## 5. Arrancar

```bash
cd /opt/abuela
docker compose up -d --build
```

Qué hace el contenedor:

1. Monta el volumen `abuela-data` en `/data`
2. Clona el repo privado en `/data/repo` (o hace `git pull` si ya existe)
3. Ejecuta `python3 descargar.py ElvaTorales1`
4. Guarda audios y estado en `/data/repo/canciones/`:
   - `manifest.json` — descargadas OK
   - `fallidas.json` — errores
   - `progreso.txt` — canción actual

---

## 6. Monitorizar

```bash
# Logs en vivo
docker compose logs -f

# Progreso
docker compose exec abuela cat /data/repo/canciones/progreso.txt

# Cuántas lleva
docker compose exec abuela python3 -c "
import json
from pathlib import Path
m = Path('/data/repo/canciones/manifest.json')
print(len(json.loads(m.read_text())) if m.exists() else 0, 'descargadas')
"

# Espacio en disco
df -h /var/lib/docker/volumes/
```

Si el contenedor termina (error o fin del script), con `restart: unless-stopped` Docker lo reinicia. El script **salta** canciones ya en `manifest.json`, así que es seguro reanudar.

---

## 7. Volumen Hetzner (opcional, más disco)

Si 80 GB del VPS no bastan:

1. Cloud Console → Volumes → Create (100 GB)
2. Attach al servidor
3. En el servidor:

```bash
mkfs.ext4 /dev/disk/by-id/scsi-0HC_Volume_XXXXX
mkdir -p /mnt/abuela
mount /dev/disk/by-id/scsi-0HC_Volume_XXXXX /mnt/abuela
echo '/dev/disk/by-id/scsi-0HC_Volume_XXXXX /mnt/abuela ext4 defaults 0 2' >> /etc/fstab
```

Cambia el volumen en `docker-compose.yml` a bind mount:

```yaml
volumes:
  - /mnt/abuela:/data
```

En lugar de `abuela-data:`.

---

## 8. Traer los archivos a tu Mac

Cuando quieras copiar las canciones:

```bash
rsync -avz --progress root@TU_IP:/var/lib/docker/volumes/abuela_abuela-data/_data/repo/canciones/ ./canciones/
```

(Si usas bind mount en `/mnt/abuela`, la ruta es `/mnt/abuela/repo/canciones/`.)

---

## 9. Actualizar el script

1. Push al repo privado
2. En el servidor:

```bash
cd /opt/abuela
docker compose restart abuela
```

El `entrypoint.sh` hace `git pull` antes de cada arranque.

---

## 10. Coste orientativo (Hetzner)

| Recurso | ~€/mes |
|---------|--------|
| CX32 (4 vCPU, 8 GB, 80 GB) | ~8–9 € |
| Volume 100 GB (opcional) | ~4–5 € |

Un CX22 (2 vCPU, 4 GB) puede ir justo con Chromium; si ves OOM, sube a CX32.

---

## Troubleshooting

| Síntoma | Solución |
|---------|----------|
| `Permission denied (publickey)` al clonar | Deploy key mal pegada en GitHub o `chmod 600 deploy-key` |
| `git pull` falla | Repo con cambios locales en el volumen; borra `/data/repo` y reinicia (pierdes solo el clone, no el volumen si separas datos) |
| Contenedor se mata / OOM | Más RAM (`shm_size` ya está en 1 GB) o CX32+ |
| `audio no cargó a tiempo` | Normal en algunas canciones; quedan en `fallidas.json` |
| Muy lento | Esperado: ~10k × ~1 min ≈ varios días |

---

## Estructura de archivos en el servidor

```
/opt/abuela/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
├── .env                 # secretos (no en git)
└── deploy-key           # clave SSH (no en git)

/var/lib/docker/volumes/abuela_abuela-data/_data/
└── repo/                # clone del repo privado
    ├── descargar.py
    └── canciones/
        ├── manifest.json
        ├── catalogo-completo.json
        └── *.m4a / *.mp4
```

---

## Checklist rápido

- [ ] VPS Hetzner con ≥ 80 GB disco y 8 GB RAM
- [ ] Repo privado con el código de despliegue
- [ ] Deploy key o token configurado
- [ ] `.env` en el servidor con `GIT_REPO_URL`
- [ ] `docker compose up -d --build`
- [ ] `docker compose logs -f` confirma clon + descarga
