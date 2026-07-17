# ASTUR Safe EA v0.40 + IA local

La IA es una segunda opinión limitada. El algoritmo determinista, el stop
loss y los límites de riesgo siempre mandan. La IA nunca puede abrir una
operación sin señal, aumentar lotes, retirar el SL ni ampliar el riesgo.
Como mucho puede vetar una entrada (`BLOCK`), acercar el SL con una fórmula
ATR fija (`PROTECT`, desactivado por defecto) o cerrar antes de tiempo
(`CLOSE`, desactivado por defecto).

**Estado: implementado.** `ASTUR_SafeEA.mq4` (desde v0.40) llama de verdad
al puente vía `WebRequest`. Sigue viniendo **apagado** (`UseLocalAI=false`)
y, al activarlo, arranca en **modo sombra** (`AIShadowMode=true`): solo
analiza y registra, nunca actúa, hasta que lo cambies tú explícitamente.

## Seguridad y separación (léelo antes de arrancar nada)

- **Solo tú puedes usar el puente.** Toda ruta (incluida `/health`) exige
  la cabecera `X-ASTUR-Token` con el valor de `ASTUR_AI_SECRET`. Sin ese
  token, o con uno incorrecto, el puente responde `401` y no hace nada
  (no consulta el modelo, no toca la base de datos). Si activas
  `UseLocalAI=true` en el EA sin rellenar `AISharedSecret`, el EA
  directamente rechaza arrancar (`InputsAreValid()` lo bloquea).
- **Genera un token propio, no uses el de ejemplo.** En el VPS:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
  Ese valor va en dos sitios que deben coincidir exactamente:
  1. Variable de entorno `ASTUR_AI_SECRET` donde arranques `astur_ai_bridge.py`.
  2. Input `AISharedSecret` en las propiedades del EA en MT4.
- **Nada de esto se sube al repositorio.** `.gitignore` en esta carpeta
  excluye `.env`, `*.secret`, la base SQLite del puente
  (`astur_ai_memory.sqlite3`) y los CSV que genera el EA en tiempo de
  ejecución (`ASTUR_Diagnostics.csv`, `ASTUR_AI_Decisions.csv`,
  `ASTUR_TradeOutcomes.csv`, `ASTUR_News.csv`). Usa `.env.example` como
  plantilla para tu `.env` real (que tampoco se sube).
- **Mantén el puente en loopback (`127.0.0.1`).** Es la protección de red
  de base: el puerto no es alcanzable desde fuera de esa máquina. El token
  compartido es una segunda capa (defensa en profundidad), no un sustituto.
  Si alguna vez cambias `ASTUR_AI_HOST` a algo distinto de loopback, el
  puente imprime una advertencia al arrancar — trátalo como una señal de
  que necesitas revisar el firewall del VPS.
- **Sobre cifrado en tránsito (TLS):** dado que EA y puente corren en la
  MISMA máquina y se hablan por `127.0.0.1`, el tráfico nunca sale a una
  red física — no hay "cable" que interceptar. Añadir HTTPS ahí exigiría un
  certificado (autofirmado, ya que es solo para loopback) que además hay
  que instalar como confiable en el almacén de certificados de Windows
  para que `WebRequest` lo acepte; en la práctica es frágil y aporta poca
  protección real frente al token compartido. Si en el futuro expones el
  puente más allá de loopback (por ejemplo, para consultarlo desde otra
  máquina), entonces sí hace falta TLS de verdad — en ese caso, usa un
  proxy inverso (Caddy, nginx, stunnel) delante del puente en vez de añadir
  TLS al propio script de Python.
- **No compartas capturas de las propiedades del EA ni tu `.set` file**:
  MT4 muestra los valores de los inputs (incluido `AISharedSecret`) en
  texto plano en la pestaña de propiedades y los guarda en claro en los
  archivos `.set`.

## Archivos

- `ASTUR_SafeEA.mq4`: asesor experto para MetaTrader 4.
- `astur_ai_bridge.py`: puente local entre MT4 y Ollama/LM Studio, con
  autenticación por token compartido.
- `.env.example`: plantilla de variables de entorno (sin secretos reales).
- `ASTUR_TradeOutcomes.csv`: lo crea el EA con el resultado final (ganancia
  o pérdida agregada, incluyendo cierres parciales) por operación. Solo se
  escribe si `UseLocalAI=true`.
- `ASTUR_AI_Decisions.csv`: lo crea el EA con cada consejo de la IA
  (evento, ticket, score de confluencia, acción, confianza, motivo, si
  estaba en modo sombra o activo).
- `astur_ai_memory.sqlite3`: lo crea el puente para conservar decisiones y
  resultados en el VPS.

## 1. Arrancar la IA local

### Ollama (opción predeterminada)

En PowerShell, dentro de la carpeta que contiene el puente:

```powershell
$env:ASTUR_AI_PROVIDER="ollama"
$env:ASTUR_AI_MODEL="qwen2.5:7b"
$env:ASTUR_AI_SECRET="<tu-token-generado>"
python .\astur_ai_bridge.py
```

El modelo tiene que existir ya en Ollama. Se puede cambiar por cualquier otro
modelo local disponible.

### LM Studio u otra API compatible con OpenAI

```powershell
$env:ASTUR_AI_PROVIDER="openai"
$env:ASTUR_AI_MODEL="nombre-del-modelo-cargado"
$env:ASTUR_AI_URL="http://127.0.0.1:1234/v1/chat/completions"
$env:ASTUR_AI_SECRET="<tu-token-generado>"
python .\astur_ai_bridge.py
```

Verificar con el mismo token (por ejemplo con `curl`):

```bash
curl -H "X-ASTUR-Token: <tu-token-generado>" http://127.0.0.1:8765/health
```

Debe responder `{"status": "ok", ...}`. Sin el header, o con el token
equivocado, debe responder `401`.

## 2. Autorizar la conexión en MT4

1. Abrir `Herramientas > Opciones > Asesores Expertos`.
2. Marcar `Permitir WebRequest para las URL indicadas`.
3. Agregar exactamente `http://127.0.0.1:8765`.
4. Confirmar con `Aceptar`.

## 3. Configurar el EA — primera fase obligatoria: modo sombra

En las propiedades del EA:

```text
UseLocalAI=true
AISharedSecret=<el mismo token que ASTUR_AI_SECRET del puente>
AIShadowMode=true
AIAllowEntryVeto=true
AIAllowProtectiveStop=false
AIAllowEarlyClose=false
```

En este modo la IA analiza y escribe sus decisiones (`ASTUR_AI_Decisions.csv`),
pero no cambia ninguna operación. Mantenerlo en una cuenta DEMO. No activar
`AIShadowMode=false` hasta reunir y revisar suficientes decisiones y
resultados fuera de muestra. El puente limita automáticamente la confianza
mientras tenga menos de `ASTUR_AI_MIN_MEMORY` (30 por defecto) resultados
cerrados; ese número es solo un mínimo técnico, no una validación suficiente.

## 4. Acciones limitadas

- `ENTRY`: la IA solo puede responder `ALLOW` o `BLOCK`. `ALLOW` nunca crea
  una entrada: la señal normal debe existir y superar todos los controles
  del EA primero. `BLOCK` solo veta si `confidence >= AIMinConfidence`
  (0.55 por defecto) y `AIShadowMode=false`.
- `MANAGE`: la IA solo puede responder `HOLD`, `PROTECT` o `CLOSE`, y se
  consulta como mucho una vez cada `AIManageIntervalSeconds` (60s por
  defecto) por operación abierta, no en cada tick — `WebRequest` es una
  llamada bloqueante, así que consultarla en cada tick pausaría el EA.
- `PROTECT` (si `AIAllowProtectiveStop=true`) solo acerca el SL mediante
  `AIProtectATRMultiple × ATR`; el código verifica explícitamente que el
  nuevo SL sea más ajustado que el actual antes de aplicarlo — nunca lo aleja.
- `CLOSE` está desactivado por defecto (`AIAllowEarlyClose=false`).
- Si la IA no responde (puente caído, timeout, `401`, etc.),
  `AIFailClosed=true` bloquea esa entrada concreta cuando el modo sombra
  está desactivado; en modo sombra, la falta de respuesta simplemente se
  registra como `SIN_RESPUESTA` y no bloquea nada.

## 5. Backtest y limitación de MT4

MetaTrader 4 no permite `WebRequest()` dentro del Strategy Tester. Por eso:

- el backtest prueba la estrategia determinista sin IA (con `UseLocalAI=false`);
- la IA se evalúa primero en demo, en modo sombra;
- `ASTUR_AI_Decisions.csv` y `ASTUR_TradeOutcomes.csv` permiten comparar lo
  que aconsejó la IA con lo que realmente ocurrió.

No se debe usar una IA generativa como garantía de beneficio. Su utilidad
aquí es rechazar situaciones dudosas y aportar una capa de análisis
auditable, no adivinar el mercado.
