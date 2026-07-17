# ASTUR Safe EA (v0.32) — EURUSD M15, MetaTrader 4

## Antes de leer nada más: lo que este EA NO es

- **No gana siempre.** Ningún sistema de trading, humano o algorítmico,
  puede garantizar ganancias ni evitar todas las pérdidas: los mercados se
  mueven por información que nadie tiene por adelantado. Si alguien te
  vende un bot con "0 pérdidas garantizadas", es una estafa. Este EA busca
  operar con una ventaja estadística razonable y un riesgo estrictamente
  limitado por operación, día, semana y drawdown — nada más.
- **No es un sistema de alta frecuencia (HFT).** MetaTrader 4 recibe los
  precios (*ticks*) que le manda el bróker, normalmente con decenas o
  cientos de milisegundos de latencia (a veces más), sin co-ubicación ni
  acceso a microestructura del order book. `OnTick()` se ejecuta con cada
  tick recibido — es lo más "en vivo" que permite esta plataforma, pero no
  equivale a un motor de trading institucional de milisegundos reales.

Cualquier otra promesa iría en contra de la seguridad del propio usuario,
así que no está incluida ni lo estará.

## Qué cambió en v0.2 respecto a v0.1

1. **Gestión de la posición abierta en cada tick** (`ManageOpenPosition`):
   - *Break-even*: al alcanzar `BreakEvenTriggerATR × ATR` de beneficio,
     el stop loss se mueve a `entrada + BreakEvenLockPips`.
   - *Trailing stop*: al superar `TrailingStartATR × ATR` de beneficio, el
     SL sigue al precio a una distancia de `TrailingStepATR × ATR`.
   - El SL **solo se mueve para reducir riesgo, nunca para aumentarlo**
     (se verifica matemáticamente en cada modificación). Se respeta el
     `MODE_STOPLEVEL` del bróker y un paso mínimo (`MinTrailingStepPips`)
     para no saturar de modificaciones al servidor.
2. **Filtros de señal reforzados** (`GetClosedBarSignal`), todos
   desactivables por separado:
   - Confirmación de tendencia en una temporalidad superior (`H1` por
     defecto) mediante EMA.
   - Filtro de pendiente de la EMA de tendencia (exige que la tendencia
     también esté avanzando, no solo que el precio esté de un lado).
   - Filtro de pendiente del ADX (exige que la fuerza de la tendencia esté
     aumentando, no debilitándose).
   - Cada filtro reduce la frecuencia de entradas a cambio de mayor
     calidad; ninguno elimina el riesgo.
3. **Filtro de horario de noticias** (`UseNewsFilter`, desactivado por
   defecto): bloquea nuevas entradas en una ventana alrededor de eventos
   económicos definidos en un CSV local.

## Qué cambió en v0.3 respecto a v0.2

"Más precisión" aquí significa: señales más selectivas, salidas más
eficientes y menos coste de transacción desperdiciado — **no** una promesa
de más ganancia garantizada (eso sigue siendo imposible). Nada de esto está
validado con backtesting real todavía; hay que probarlo en el Strategy
Tester antes de confiar en ello.

1. **Entrada por puntuación de confluencia** (`BuildSignalContext`): los
   tres filtros añadidos en v0.2 (confirmación H1, pendiente de tendencia,
   pendiente de ADX) dejaron de ser un `AND` rígido — ahora cada uno suma
   un punto y se exige un mínimo (`MinimumConfluenceScore`, por defecto 2
   de un máximo de 3 filtros activos). Encadenar condiciones obligatorias
   tiende a sobreajustar y a dejar el sistema sin operar casi nunca; un
   sistema de puntos es más flexible sin renunciar a la calidad. El núcleo
   de la señal (cruce de EMAs + posición respecto a la EMA de tendencia +
   ADX mínimo + dirección del DI) sigue siendo obligatorio, no puntuable.
2. **Cierre parcial por múltiplo del riesgo inicial** (`UsePartialClose`):
   al alcanzar `PartialCloseAtR × R` de beneficio (donde R es la distancia
   real al SL con la que se abrió la operación, no el ATR actual), se
   cierra `PartialClosePct`% del lote y se deja correr el resto con el
   breakeven/trailing ya existentes. Reduce la varianza asegurando parte
   del beneficio sin renunciar a las tendencias largas.
3. **Filtro de coste de transacción** (`MaxSpreadToSLRatio`): además del
   límite absoluto de spread (`MaxSpreadPips`), rechaza la entrada si el
   spread actual supera un porcentaje del stop loss planeado. Un SL muy
   ajustado (volatilidad baja) con spread alto destruye la esperanza
   matemática aunque la señal sea técnicamente correcta.
4. **Log de diagnóstico en CSV** (`UseDiagnosticsLog`): registra, en cada
   vela M15 cerrada, todos los valores de indicadores, el cruce detectado,
   la puntuación de confluencia, si hubo señal final, si algún filtro la
   bloqueó (spread, noticias, sesión, etc.) y el resultado de la orden si
   se abrió. Se guarda en `MQL4/Files/ASTUR_Diagnostics.csv`. La idea es
   que tú puedas analizarlo en Excel/Python para ver qué filtros realmente
   aportan y cuáles solo recortan operaciones sin mejorar el resultado —
   en vez de que se decida por intuición.

## Qué cambió en v0.31 / v0.32

- **v0.31**: el spread se compara en puntos enteros (`MODE_SPREAD`) en vez
  de pips como `double`, evitando falsos rechazos por redondeo de coma
  flotante. El log de diagnóstico ahora también registra el motivo cuando
  `ExecuteSignal` cancela una orden (antes ese caso quedaba sin explicar).
- **v0.32**: el cierre parcial (`UsePartialClose`) ahora indexa su estado
  ("¿ya se hizo el cierre parcial de esta operación?") por la **hora de
  apertura de la operación**, no por el número de ticket. Si el bróker
  reasigna el ticket al ejecutar un cierre parcial, la v0.3/v0.31 podían
  malinterpretarlo como una operación nueva y repetir el cierre parcial en
  cada tick siguiente hasta agotar el lote. v0.32 relocaliza la orden por
  posición (magic number + símbolo) después de cada intento de cierre
  parcial en vez de asumir que el ticket no cambió.

## IA local: solo diseño por ahora, no implementada en el EA

Esta carpeta incluye `astur_ai_bridge.py` (un servidor HTTP local que
consulta un modelo en Ollama/LM Studio y guarda memoria en SQLite) y
`ASTUR_AI_SETUP.md` (el diseño de cómo se conectaría con el EA: modo
sombra, acciones limitadas ALLOW/BLOCK/HOLD/PROTECT/CLOSE, etc.).

**`ASTUR_SafeEA.mq4` todavía no llama a ese puente.** No hay inputs
`UseLocalAI`/`AIShadowMode`, ninguna llamada `WebRequest`, ni escritura de
`ASTUR_AI_Decisions.csv`/`ASTUR_TradeOutcomes.csv`. El puente funciona por
sí solo (se puede arrancar y probar con `/health`), pero la integración del
lado MQL4 es trabajo pendiente — ver `ASTUR_AI_SETUP.md` para el diseño
previsto antes de construirla.

## Limitación honesta del filtro de noticias

MQL4 **no tiene acceso nativo a un calendario económico ni a internet**
sin configuración adicional (`WebRequest` requiere URLs en lista blanca en
Herramientas → Opciones → Asesores Expertos, y no existe una API gratuita
fiable integrada). Por eso el filtro lee un **archivo CSV local**, no
descarga nada:

- Ubicación: `MQL4/Files/ASTUR_News.csv` (carpeta de datos del terminal,
  accesible desde el Navegador → clic derecho en el EA → "Abrir carpeta de
  datos").
- Formato, una línea por evento, **sin cabecera**:
  ```
  YYYY.MM.DD,HH:MM,IMPACTO
  ```
  Ejemplo (ver `ASTUR_News_ejemplo.csv`):
  ```
  2026.07.16,14:30,HIGH
  2026.07.17,08:30,MEDIUM
  2026.07.18,12:15,HIGH
  ```
- La hora debe estar en **hora del servidor del bróker** (la misma que usa
  `TimeCurrent()`), no necesariamente UTC.
- `NewsImpactFilter` (por defecto `"HIGH"`) decide qué impactos bloquean
  entradas; para incluir varios, usa `"HIGH,MEDIUM"`.
- Tú (o un script externo que tú mismo ejecutes) eres responsable de
  mantener ese CSV actualizado con los eventos del calendario económico
  que te interese. El EA solo lo relee cada `NewsReloadMinutes`.
- **Comportamiento fail-safe**: si activas `UseNewsFilter` y el archivo no
  existe o no se puede leer, el EA **bloquea todas las entradas nuevas**
  hasta que lo corrijas — nunca al revés. Esto se ve reflejado en el
  panel del gráfico ("Noticias: ACTIVO, archivo no encontrado").

## Cómo probarlo

1. Cárgalo en el Strategy Tester de MT4 sobre `EURUSD`, `M15`, con datos
   de varios años y modelo "Cada tick" para una simulación más realista.
2. Después, en una **cuenta DEMO** separada, déjalo correr en vivo un
   tiempo razonable antes de considerar cualquier otra cosa.
3. `AllowRealAccount` sigue en `false` por defecto: hay que cambiarlo
   explícitamente, y aun así el EA no promete resultados en real.

## Inputs nuevos (resumen)

| Input | Por defecto | Qué hace |
|---|---|---|
| `UseHigherTimeframeFilter` | `true` | Suma un punto de confluencia si H1 confirma la dirección de M15 |
| `HigherTimeframe` | `PERIOD_H1` | Temporalidad usada para esa confirmación |
| `HigherTrendEMAPeriod` | `200` | Periodo de la EMA de tendencia en esa temporalidad |
| `UseTrendSlopeFilter` | `true` | Suma un punto si la EMA de tendencia M15 tiene pendiente a favor |
| `UseADXSlopeFilter` | `true` | Suma un punto si el ADX está subiendo (tendencia reforzándose) |
| `MinimumConfluenceScore` | `2` | Puntos mínimos (de los filtros activos arriba) para permitir la entrada |
| `UseBreakEven` / `BreakEvenTriggerATR` / `BreakEvenLockPips` | `true` / `1.0` / `1.0` | Mueve el SL a breakeven al alcanzar cierto beneficio (múltiplo de ATR en vivo) |
| `UseTrailingStop` / `TrailingStartATR` / `TrailingStepATR` / `MinTrailingStepPips` | `true` / `1.5` / `1.0` / `0.5` | Trailing stop basado en ATR en vivo |
| `UsePartialClose` / `PartialCloseAtR` / `PartialClosePct` | `true` / `1.0` / `50.0` | Cierra parte del lote al alcanzar N × R de beneficio (R = riesgo inicial real) |
| `MaxSpreadToSLRatio` | `0.20` | Rechaza la entrada si el spread supera este % del SL planeado |
| `UseNewsFilter` / `NewsFileName` / `NewsBufferMinutesBefore` / `NewsBufferMinutesAfter` / `NewsImpactFilter` / `NewsReloadMinutes` | `false` / `ASTUR_News.csv` / `30` / `15` / `HIGH` / `60` | Filtro de noticias vía CSV local |
| `UseDiagnosticsLog` / `DiagnosticsFileName` | `true` / `ASTUR_Diagnostics.csv` | Log CSV de cada señal evaluada, tomada o bloqueada |

Todos los filtros nuevos se pueden desactivar individualmente desde las
propiedades del EA para volver a un comportamiento más parecido a v0.1.

## Cómo usar el log de diagnóstico para decidir qué de verdad ayuda

1. Corre el EA en Strategy Tester con `UseDiagnosticsLog=true` sobre varios
   años de datos.
2. Abre `ASTUR_Diagnostics.csv` (carpeta `MQL4/Files/`, o `Tester/Files/`
   si corrió en el Strategy Tester) en Excel/Python.
3. Compara: ¿cuántas señales con `Senal=BUY/SELL` fueron bloqueadas por
   `Bloqueo` (spread, noticias, sesión...)? ¿El `ConfluenceScore` de las
   operaciones ganadoras es sistemáticamente más alto que el de las
   perdedoras? Eso te dice si el filtro correspondiente realmente aporta
   o si solo está recortando operaciones al azar.
4. Ajusta un input a la vez y vuelve a correr — cambiar varios a la vez
   hace imposible saber cuál causó la diferencia.
