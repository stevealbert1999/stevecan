> **Estado actual (importante):** este documento describe el diseño
> planeado de la integración IA (inputs `UseLocalAI`, `AIShadowMode`, etc.,
> llamadas `WebRequest`, ficheros `ASTUR_AI_Decisions.csv` y
> `ASTUR_TradeOutcomes.csv`). **Nada de eso está todavía implementado en
> `ASTUR_SafeEA.mq4`** (versión actual: v0.32). El único componente que
> funciona por sí solo es `astur_ai_bridge.py` (el servidor HTTP local). El
> EA aún no le hace ninguna llamada. Los pasos 2 a 5 de abajo no tendrán
> ningún efecto hasta que se escriba esa integración del lado MQL4.

# ASTUR Safe EA v0.32 + IA local (diseño, pendiente de implementar en el EA)

La IA es una segunda opinion limitada. El algoritmo normal, el stop loss y
los limites de riesgo siempre mandan. La IA nunca puede abrir una operacion
sin senal, aumentar lotes, retirar el SL ni ampliar el riesgo.

## Archivos

- `ASTUR_SafeEA.mq4`: asesor experto para MetaTrader 4.
- `astur_ai_bridge.py`: puente local entre MT4 y Ollama/LM Studio.
- `ASTUR_TradeOutcomes.csv`: lo crearía el EA con el resultado final por
  señal (pendiente de implementar).
- `ASTUR_AI_Decisions.csv`: lo crearía el EA con cada consejo de la IA
  (pendiente de implementar).
- `astur_ai_memory.sqlite3`: lo crea el puente para conservar decisiones y
  resultados en el VPS (esto sí funciona ya, de forma independiente).

## 1. Arrancar la IA local

### Ollama (opcion predeterminada)

En PowerShell, dentro de la carpeta que contiene el puente:

```powershell
$env:ASTUR_AI_PROVIDER="ollama"
$env:ASTUR_AI_MODEL="qwen2.5:7b"
python .\astur_ai_bridge.py
```

El modelo tiene que existir ya en Ollama. Se puede cambiar por cualquier otro
modelo local disponible.

### LM Studio u otra API compatible con OpenAI

```powershell
$env:ASTUR_AI_PROVIDER="openai"
$env:ASTUR_AI_MODEL="nombre-del-modelo-cargado"
$env:ASTUR_AI_URL="http://127.0.0.1:1234/v1/chat/completions"
python .\astur_ai_bridge.py
```

Abrir `http://127.0.0.1:8765/health` en el navegador del VPS. Debe responder
con `status: ok`. Esto ya se puede probar hoy — es independiente del EA.

## 2. Autorizar la conexion en MT4 (para cuando exista la integración)

1. Abrir `Herramientas > Opciones > Asesores Expertos`.
2. Marcar `Permitir WebRequest para las URL indicadas`.
3. Agregar exactamente `http://127.0.0.1:8765`.
4. Confirmar con `Aceptar`.

## 3. Primera fase obligatoria: modo sombra (diseño)

En las propiedades del EA, una vez exista la integración:

```text
UseLocalAI=true
AIShadowMode=true
AIAllowEntryVeto=true
AIAllowProtectiveStop=false
AIAllowEarlyClose=false
```

En este modo la IA analiza y escribe sus decisiones, pero no cambia ninguna
operacion. Mantenerlo en una cuenta demo. No activar acciones reales hasta
reunir y revisar suficientes decisiones y resultados fuera de muestra.
El puente limita automaticamente la confianza mientras tenga menos de 30
resultados cerrados; 30 es solo un minimo tecnico, no una validacion suficiente.

## 4. Acciones limitadas (diseño)

- `ENTRY`: la IA solo podría responder `ALLOW` o `BLOCK`. `ALLOW` nunca
  crearía una entrada: la senal normal debe existir y superar todos los
  controles.
- `MANAGE`: la IA solo podría responder `HOLD`, `PROTECT` o `CLOSE`.
- `PROTECT` solo acercaría el SL mediante una formula ATR fija; nunca lo
  alejaría.
- `CLOSE` estaría desactivado por defecto.
- Si la IA no responde, `AIFailClosed=true` bloquearía nuevas entradas
  cuando el modo sombra esté desactivado.

## 5. Backtest y limitacion de MT4

MetaTrader 4 no permite `WebRequest()` dentro del Strategy Tester. Por eso,
incluso una vez implementada la integración:

- el backtest prueba la estrategia determinista sin IA;
- la IA se evalua primero en demo, en modo sombra;
- los archivos `ASTUR_AI_Decisions.csv` y `ASTUR_TradeOutcomes.csv`
  permitirían comparar lo que aconseje la IA con lo que realmente ocurrió.

No se debe usar una IA generativa como garantia de beneficio. Su utilidad
prevista aquí es rechazar situaciones dudosas y aportar una capa de análisis
auditable, no adivinar el mercado.
