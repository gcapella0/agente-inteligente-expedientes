# CHANGELOG

## [1.0.0] - 2026-05-08 - Defensa de Tesis

### FASE 2: Expedientes Completo
- Busqueda de docentes con filtros (nombre, departamento, sede, status)
- Modal de edicion con 11 campos dinamicos y layout responsivo (1 col movil, 2 tablet, 3 escritorio)
- Vista de detalle completa con KPIs de completitud
- Visor de documentos con dos pestanas: Documento (preview imagen / descarga PDF) y JSON OCR
- Botones: Ver OCR, Eliminar documento
- Tabla con columnas Formato y Tamaño leidas desde `archivo.formato` / `archivo.tamano_bytes`

### FASE 3: Chat IA para Expedientes
- Endpoint `POST /expedientes/{cedula}/chat` con autenticacion JWT
- RAG: carga contexto estructurado desde MongoDB (docente + documentos + OCR)
- Soporte para OpenRouter (con fallback automatico entre 6 modelos) y Ollama (local)
- OCR estructurado: incluye `campos_extraidos` por documento en el contexto
- Parsing especial para `curriculo_vitae`: extrae cada titulo de la seccion Education con fecha inicio-fin, especializacion e institucion
- Sistema prompt optimizado: temperatura 0.2, max_tokens 300 para respuestas cortas y precisas
- Contexto compacto: max 8 documentos, 500 chars OCR por doc, limite total 6000 chars con re-truncado automatico
- Boton "Parar" en el frontend para cancelar peticiones en curso via AbortController
- Auditoria de consultas en coleccion `auditoria` (tolerante a fallo de MongoDB)
- 6 tests automatizados (exito, 404, 400, 503, verificacion de no-llamada en path error)

### Optimizaciones de rendimiento
- Contexto compacto sin desperdicio de tokens (reduccion de ~16000 a 6000 chars maximos)
- Temperatura baja (0.2) para maximizar precision y reducir variabilidad
- Max tokens reducido (300 vs 800) para respuestas mas rapidas
- Timeouts ajustados: 30s OpenRouter, 60s Ollama

### Mejoras anteriores (acumuladas en esta rama)
- Visor de documentos con soporte para archivos del endpoint `/archivo` autenticado via token en query param
- Panel de chat IA integrado al final de `expediente.html` con historial scrolleable
- Toggle Enviar/Parar con estado Alpine (`x-show`, no `disabled`)

---

## [0.9.0] - Metricas, Usuarios y Config Agentes
- GET /metricas/: 4 KPIs del sistema (10 tests)
- CRUD /usuarios/: gestion de usuarios, solo admin (23 tests)
- GET/PUT /config/agentes: parametros de los 4 agentes (14 tests)

## [0.8.0] - API REST Fase 6
- Control de agentes: GET /agentes, POST ejecutar (pipeline / independiente), POST stop
- Configuracion LLM en caliente: GET/PUT /config/llm, POST /config/llm/probar
- Logs SSE: GET /logs/stream (filtros agente/nivel), GET /logs/descargar (34 tests)

## [0.7.0] - API REST Fase 5
- Autenticacion JWT: POST login, crear-usuario, cambiar-password
- Auditoria admin: GET /admin/auditoria/expediente, /documento (32 tests)

## [0.6.0] - API REST Fase 4
- Escritura CRUD con JWT: PUT/DELETE expediente, POST/PATCH/DELETE documentos (26 tests)

## [0.5.0] - API REST Fases 1-3
- Health, expedientes, documentos, catalogos (30 tests)
- Estadisticas y validacion (31 tests)
- Busqueda full-text, exportacion JSON/XML/CSV, cursor pagination (22 tests)

## [0.4.0] - StorageAgent + Compresion
- Almacenamiento en MongoDB con compresion Ghostscript/Pillow
- Enriquecimiento del perfil del docente desde curriculo vitae (83 tests)

## [0.3.0] - ClassifierAgent + Proveedores LLM
- Clasificacion de 22 tipos de documento via LLM
- OpenRouterProvider (rotacion de modelos) + OllamaProvider (local CPU)
- Factory `create_llm_provider()` con configuracion desde MongoDB (48 + 30 tests)

## [0.2.0] - OcrAgent
- Extraccion de texto con docTR, json_ligero para LLM, deduplicacion por hash (57 tests)

## [0.1.0] - WatcherAgent
- Monitoreo IMAP Gmail, deduplicacion UID + fingerprint, extraccion de nombre (47 tests)
