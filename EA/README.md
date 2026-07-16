# ASTUR Safe EA (v0.2) — EURUSD M15, MetaTrader 4

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
| `UseHigherTimeframeFilter` | `true` | Exige que H1 confirme la dirección de M15 |
| `HigherTimeframe` | `PERIOD_H1` | Temporalidad usada para esa confirmación |
| `HigherTrendEMAPeriod` | `200` | Periodo de la EMA de tendencia en esa temporalidad |
| `UseTrendSlopeFilter` | `true` | Exige que la EMA de tendencia M15 tenga pendiente a favor |
| `UseADXSlopeFilter` | `true` | Exige que el ADX esté subiendo (tendencia reforzándose) |
| `UseBreakEven` / `BreakEvenTriggerATR` / `BreakEvenLockPips` | `true` / `1.0` / `1.0` | Mueve el SL a breakeven al alcanzar cierto beneficio |
| `UseTrailingStop` / `TrailingStartATR` / `TrailingStepATR` / `MinTrailingStepPips` | `true` / `1.5` / `1.0` / `0.5` | Trailing stop basado en ATR en vivo |
| `UseNewsFilter` / `NewsFileName` / `NewsBufferMinutesBefore` / `NewsBufferMinutesAfter` / `NewsImpactFilter` / `NewsReloadMinutes` | `false` / `ASTUR_News.csv` / `30` / `15` / `HIGH` / `60` | Filtro de noticias vía CSV local |

Todos los filtros nuevos se pueden desactivar individualmente desde las
propiedades del EA para volver al comportamiento equivalente a v0.1.
