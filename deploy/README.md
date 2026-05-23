# Guía de despliegue — UNEGIA (Servidor UNEG)

## Prerequisitos

El servidor debe tener instalados y operativos:

- **MongoDB** corriendo en el host en el puerto 27017
- **Ollama** corriendo en el host en el puerto 11434 con el modelo `gemma3:12b` disponible
  ```bash
  ollama pull gemma3:12b
  ollama serve   # si no está como servicio del sistema
  ```
- **Git** para clonar el repositorio
- **Docker 28+** y **Docker Compose v2** instalados

## Instalación

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio> agente-expedientes
cd agente-expedientes
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
nano .env
```

Variables críticas que deben completarse:

| Variable | Descripción | Ejemplo |
|---|---|---|
| `JWT_SECRET_KEY` | Clave secreta para firmar tokens JWT | ver abajo |
| `MONGO_URI` | URI de conexión a MongoDB | `mongodb://host.docker.internal:27017` |
| `MONGO_DB` | Nombre de la base de datos | `expedientes_uneg` |
| `OLLAMA_HOST` | URL de Ollama en el host | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Modelo a usar | `gemma3:12b` |
| `LLM_PROVIDER` | Proveedor LLM activo | `ollama` |
| `MAIL_USER` | Correo Gmail para el watcher | `cuenta@gmail.com` |
| `MAIL_PASS` | Contraseña de aplicación Gmail | (ver Google Account) |

Generar `JWT_SECRET_KEY`:

```bash
openssl rand -hex 32
```

### 3. Crear directorios de datos

```bash
mkdir -p data/input data/storage logs
```

### 4. Construir la imagen

```bash
docker compose build
```

La primera vez descarga dependencias Python y modelos de docTR (~500 MB). Puede tardar varios minutos.

### 5. Iniciar el servicio

```bash
docker compose up -d
```

### 6. Verificar que levantó correctamente

```bash
curl http://localhost:8000/health
```

Respuesta esperada: `{"status": "ok", ...}`

La interfaz web está disponible en: `http://<ip-del-servidor>:8000/ui/`

Credenciales por defecto del primer inicio: `admin@uneg.edu.ve` / `admin123`
**Cambiar la contraseña inmediatamente tras el primer login.**

---

## Comandos de operación

### Ver logs en tiempo real

```bash
docker compose logs -f
```

### Reiniciar el servicio

```bash
docker compose restart
```

### Detener el servicio

```bash
docker compose down
```

### Actualizar a una nueva versión

```bash
git pull
docker compose build
docker compose up -d
```

### Ver estado del contenedor

```bash
docker compose ps
```

### Acceder al shell del contenedor

```bash
docker compose exec agente-expedientes bash
```

---

## Notas de red

El contenedor accede a MongoDB y Ollama del host mediante `host.docker.internal`, que se resuelve automáticamente gracias a `extra_hosts: host.docker.internal:host-gateway` en el Compose.

Verificar que MongoDB acepta conexiones desde Docker (por defecto `bind_ip: 127.0.0.1` solo escucha en loopback). Editar `/etc/mongod.conf`:

```yaml
net:
  bindIp: 0.0.0.0
```

Y reiniciar: `sudo systemctl restart mongod`

Lo mismo aplica si Ollama está configurado solo en loopback; verificar con `curl http://localhost:11434/api/tags`.
