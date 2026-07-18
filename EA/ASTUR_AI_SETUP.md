# ASTUR Safe EA v0.42 + IA local

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

## Contexto de mercado en vivo (v0.41)

Cada consulta a la IA (`ENTRY` o `MANAGE`) incluye un objeto `market`
recalculado **en el instante de esa consulta**, no datos guardados de
cuando se abrió la operación:

- `bid`, `ask`, `spread_pips`: precio y spread actuales.
- `ema_fast`, `ema_slow`, `ema_trend`, `adx`, `di_plus`, `di_minus`,
  `atr_pips`: indicadores recalculados en el momento.
- `weekday`, `hour`: para que la IA tenga noción de sesión/horario.
- `current_bar_m15`: la vela M15 todavía en formación (OHLC parcial).
- `candles_m15`: las últimas `AIContextCandlesM15` velas M15 **cerradas**
  (20 por defecto), en orden cronológico.
- `candles_htf`: las últimas `AIContextCandlesHTF` velas de la temporalidad
  superior configurada en `HigherTimeframe` (10 por defecto, H1 si no se
  cambió), también cerradas y en orden cronológico.

Esto le da a la IA movimiento real reciente del gráfico (no solo un puñado
de valores sueltos) para razonar sobre tendencia, momentum y estructura
antes de vetar una entrada o sugerir `PROTECT`/`CLOSE`. Sigue siendo, eso
sí, "en vivo" en el sentido de MT4: un snapshot recalculado en cada
consulta puntual (cada nueva vela M15 para `ENTRY`, cada
`AIManageIntervalSeconds` para `MANAGE`), no un flujo continuo — ver la
nota sobre `WebRequest` bloqueante más abajo.

`AIContextCandlesM15=0` / `AIContextCandlesHTF=0` desactivan el envío de
esa serie de velas (el resto del snapshot se sigue enviando) si quieres
peticiones más ligeras/rápidas para un modelo local lento.

## Gestión (MANAGE) asíncrona: WebRequest ya no bloquea el EA (v0.42)

`WebRequest` es sincrónica en MQL4: no existe una versión "async" nativa
en el lenguaje. Antes de v0.42, cada consulta `MANAGE` dejaba el EA (y en
la práctica la terminal) parado hasta `AITimeoutMs` (8s por defecto) cada
`AIManageIntervalSeconds`. Desde v0.42, con `UseAsyncManage=true` (por
defecto), eso ya no ocurre:

1. El EA escribe un archivo de petición (`AIAsyncRequestFileName`,
   `ASTUR_AI_ManageRequest.json` por defecto) con el contexto completo
   (igual que antes) y sigue con su tick normal — no espera nada.
2. Un hilo del puente (`file_watcher_loop`, activo solo si configuras
   `ASTUR_AI_MQL4_FILES_DIR`) detecta ese archivo, consulta el modelo con
   toda la calma que necesite y escribe la respuesta en
   `AIAsyncResponseFileName` (`ASTUR_AI_ManageResponse.txt` por defecto).
3. El EA, en ticks posteriores, solo comprueba si ese archivo ya existe
   (`FileIsExist`, prácticamente instantáneo) — nunca vuelve a bloquear.
   Si no hay respuesta al cabo de `AIAsyncTimeoutSec` (45s por defecto), se
   registra como `SIN_RESPUESTA` y se libera el turno para la próxima
   consulta, sin haber congelado el EA en ningún momento.

Cada petición lleva un `request_id` único; si la respuesta no coincide (o
si la operación sobre la que se preguntó ya cambió o se cerró mientras se
esperaba), se descarta sin actuar — nunca se aplica una decisión a la
operación equivocada.

**Requisito:** `ASTUR_AI_MQL4_FILES_DIR` (variable de entorno del puente,
ver `.env.example`) debe apuntar a la MISMA carpeta `MQL4/Files` que usa
la terminal donde corre el EA (en MT4: `Archivo > Abrir carpeta de datos >
MQL4 > Files`). Sin esa variable configurada, el vigilante de archivos no
arranca y `UseAsyncManage=true` se queda esperando una respuesta que nunca
llega (siempre acabará en timeout) — en ese caso, o configuras la carpeta,
o pones `UseAsyncManage=false` para volver al modo síncrono/bloqueante de
antes.

**Nota de seguridad:** esta vía no pasa por `AISharedSecret` (no es una
petición de red, es la misma máquina leyendo/escribiendo archivos en su
propio disco). Su seguridad depende de los permisos del sistema de
archivos sobre esa carpeta — normal en un VPS de un solo usuario, pero
tenlo en cuenta si alguna vez compartes esa máquina con otras cuentas.

`ENTRY` (el veto de entrada) sigue siendo síncrono a propósito: ocurre como
mucho una vez cada 15 minutos (al cerrar una vela M15 con señal válida),
así que el coste de una espera acotada ahí es mucho menor que hacerlo
esperar varios ticks a media vela — y evita la complejidad de "entrada
pendiente de IA" mientras el precio sigue moviéndose.

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
- `ASTUR_AI_ManageRequest.json` / `ASTUR_AI_ManageResponse.txt`: cola de
  archivos para `MANAGE` asíncrono (ver arriba). Se crean y borran solos en
  `MQL4/Files`; no hace falta tocarlos a mano.

## 1. Arrancar la IA local

### Ollama (opción predeterminada)

En PowerShell, dentro de la carpeta que contiene el puente:

```powershell
$env:ASTUR_AI_PROVIDER="ollama"
$env:ASTUR_AI_MODEL="qwen2.5:7b"
$env:ASTUR_AI_SECRET="<tu-token-generado>"
$env:ASTUR_AI_MQL4_FILES_DIR="C:\Users\<tu-usuario>\AppData\Roaming\MetaQuotes\Terminal\<hash>\MQL4\Files"
python .\astur_ai_bridge.py
```

El modelo tiene que existir ya en Ollama. Se puede cambiar por cualquier otro
modelo local disponible. `ASTUR_AI_MQL4_FILES_DIR` es lo que activa la cola
de archivos para `MANAGE` asíncrono (ver sección anterior); si lo omites,
el puente sigue funcionando solo por HTTP (`ENTRY` funciona igual, `MANAGE`
necesitaría `UseAsyncManage=false` en el EA para no quedarse en timeout).

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
  consulta como mucho una vez cada `AIManageIntervalSeconds` (20s por
  defecto) por operación abierta, no en cada tick. Desde v0.42 es
  asíncrona por defecto (`UseAsyncManage=true`, ver sección dedicada más
  arriba), así que ese intervalo ya no bloquea el EA — se puede bajar sin
  miedo a que la terminal se quede pausada.
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
