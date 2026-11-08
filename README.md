# ia-ml-service

Modelos de ML/DL, agentes de IA, orquestador de sagas, reportes generativos, KPIs y el asistente de Telegram.

| | |
|---|---|
| Stack | Python 3.12 · FastAPI |
| Arquitectura de código | En capas (api → services → data/models) |
| Base de datos | PostgreSQL de lectura CQRS + DynamoDB |
| Nube de despliegue | AWS (EKS) |
| Puerto local | `8084` (dentro del contenedor, `8080`) |

Telegram: con `TELEGRAM_RECEPCION=n8n` recibe los mensajes de n8n en `POST /agentes/telegram/evento`; con `interna` hace polling por su cuenta.

## Probar

```bash
python -m pytest -q
docker build -t ia-ml-service .
```

## Ejecutar con todo el sistema

Este repositorio es solo un microservicio. Para levantar el sistema completo (bases de datos, Keycloak, gateways, frontends) usa
[`comedor-infra`](https://github.com/JulioCesarTA/comedor-infra) con los demás repositorios clonados en la misma carpeta:

```bash
git clone https://github.com/JulioCesarTA/comedor-infra && cd comedor-infra && bash clonar-todo.sh
docker compose up -d --build
```

## CI/CD

- `.github/workflows/ci.yml`: pruebas y construcción de la imagen en cada push y pull request.
- `.github/workflows/cd.yml`: construye y sube la imagen al registro de AWS y aplica el manifiesto de
  `comedor-infra/infra/k8s/aws/ia-ml-service/`. Secretos necesarios: ver el propio archivo.
