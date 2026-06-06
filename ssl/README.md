# HTTPS local para chefsync-agent

Si Chrome sigue bloqueando `http://localhost:5321` desde `https://dashboard.chefsync.app`,
la solución definitiva es correr el agent en HTTPS local.

## Instalar mkcert

```bash
# macOS
brew install mkcert
mkcert -install          # instala el CA raíz en el sistema/navegador

# Windows (PowerShell como Admin)
choco install mkcert
mkcert -install

# Linux
# https://github.com/FiloSottile/mkcert#linux
```

## Generar certificado para localhost

```bash
cd chefsync-agent/ssl/
mkcert localhost 127.0.0.1 ::1
# Genera: localhost+2.pem (cert) y localhost+2-key.pem (key)
```

## Activar HTTPS en el agent

Setear estas variables de entorno (o agregarlas al config.json):

```bash
CHEFSYNC_SSL_CERT=ssl/localhost+2.pem
CHEFSYNC_SSL_KEY=ssl/localhost+2-key.pem
```

El agent detecta estas vars y levanta en https://localhost:5321 automáticamente.

## Frontend

Cambiar NEXT_PUBLIC_AGENT_URL (o localStorage chefsync:agentUrl) a:
```
https://localhost:5321
```

O no hacer nada: el código de migración en agentClient.ts detecta si el cert
existe y actualiza el URL automáticamente (si se implementa la detección).

## Sin mkcert (adhoc self-signed)

Flask puede usar un cert adhoc sin instalar nada:
```
CHEFSYNC_SSL_ADHOC=true
pip install pyOpenSSL
```

Pero el browser mostrará "Certificado no confiable" y el fetch fallará igual
porque la cert no está en el store del sistema. **Usar mkcert es la única
opción que funciona sin intervención del usuario**.
