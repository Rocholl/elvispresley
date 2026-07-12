# Despliegue en VPS Hetzner — Abuela (descarga Smule)

Guía para levantar el descargador en un servidor Hetzner con Docker Compose, clonando el repo [elvispresley](https://github.com/Rocholl/elvispresley) en un volumen persistente y dejando que el contenedor descargue las canciones solas.

---

## Resumen

| Qué | Detalle |
|-----|---------|
| Objetivo | Descargar ~10.000 grabaciones de Smule (`ElvaTorales1`) |
| Runtime | Python 3 + Playwright (Chromium headless) |
| Persistencia | Volumen Docker `abuela-data` → `/data/repo` (código + `canciones/`) |
| Repo | `https://github.com/Rocholl/elvispresley` (público; HTTPS sin clave) |
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

## 2. Acceso al repo (elvispresley es público)

No hace falta deploy key. El `.env.example` ya trae:

```env
GIT_REPO_URL=https://github.com/Rocholl/elvispresley.git
```

### Si más adelante lo haces privado

1. Genera deploy key: `ssh-keygen -t ed25519 -f deploy-key -N ""`
2. Añádela en GitHub → **elvispresley** → Settings → Deploy keys
3. En el servidor:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
# edita .env: GIT_REPO_URL=git@github.com:Rocholl/elvispresley.git
```

---

## 3. ~~Subir el proyecto al repo~~ (ya está en GitHub)

Repo: **https://github.com/Rocholl/elvispresley**

---

## 4. Configurar el servidor

Conéctate:

```bash
ssh root@TU_IP_HETZNER
```

### Instalar Docker

```bash
apt update && apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
```

### Clonar y arrancar (todo desde el repo)

```bash
git clone https://github.com/Rocholl/elvispresley.git /opt/elvispresley
cd /opt/elvispresley
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` crea `.env` si no existe, construye la imagen y levanta el contenedor.

### Manual (equivalente)

```bash
git clone https://github.com/Rocholl/elvispresley.git /opt/elvispresley
cd /opt/elvispresley
cp .env.example .env
docker compose up -d --build
```

---

## 5. Arrancar

Si no usaste `./deploy.sh`:

```bash
cd /opt/elvispresley
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
cd /opt/elvispresley
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
/opt/elvispresley/          # git clone en el servidor (build context)
├── docker-compose.yml
├── deploy.sh
├── .env
└── ...

/var/lib/docker/volumes/elvispresley_abuela-data/_data/
└── repo/                   # clone dentro del volumen (código + canciones)
    ├── descargar.py
    └── canciones/
```

---

## Checklist rápido

- [ ] VPS Hetzner con ≥ 80 GB disco y 8 GB RAM
- [ ] Repo clonado en `/opt/elvispresley`
- [ ] `./deploy.sh` o `docker compose up -d --build`
- [ ] `docker compose logs -f` confirma clon + descarga
