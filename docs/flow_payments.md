# Descargas pagadas (Flow.cl)

Este repositorio incluye un flujo básico para exigir pago antes de habilitar la **descarga** de videos (no afecta la reproducción).

## Configuración

Variables de entorno (ver [cms/settings.py](../cms/settings.py)):

- `VIDEO_DOWNLOAD_REQUIRES_PAYMENT` (`true|false`)
- `VIDEO_DOWNLOAD_PRICE_CLP` (por defecto `990`)
- `VIDEO_DOWNLOAD_CURRENCY` (por defecto `CLP`)

Flow:

- `FLOW_API_KEY`
- `FLOW_SECRET_KEY`
- `FLOW_API_BASE` (por defecto `https://www.flow.cl/api`)
- `FLOW_CREATE_PATH` (por defecto `/payment/create`)
- `FLOW_STATUS_PATH` (por defecto `/payment/getStatus`)
- `FLOW_TIMEOUT_SECONDS` (por defecto `20`)

Dev only:

- `FLOW_FAKE_SUCCESS=true` concede entitlement sin llamar a Flow.

Opcional (Nginx):

- `PAYMENTS_X_ACCEL_REDIRECT_PREFIX` para servir archivos con `X-Accel-Redirect`.

## Endpoints

- `GET /api/v1/media/<friendly_token>/download/checkout/` inicia el checkout en Flow (requiere login)
- `POST /payments/flow/confirm/` webhook de confirmación (server-to-server)
- `GET /payments/flow/return/` retorno del usuario desde Flow
- `GET /api/v1/media/<friendly_token>/download/file/?encoding_id=...` descarga encoding
- `GET /api/v1/media/<friendly_token>/download/file/?kind=original` descarga original

## Notas

- El backend expone en el detalle de media (`/api/v1/media/<token>`) los campos:
  - `download_requires_payment`, `download_entitled`, `download_checkout_url`, `download_options`
- El frontend usa `download_options` para construir el menú de descargas.
