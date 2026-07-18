#property strict
#property version   "0.42"
#property description "ASTUR Safe EA: prototipo demo-first para EURUSD M15"
#property description "Sin martingala, grid ni promedios. SL obligatorio y riesgo limitado."
#property description "v0.2: gestion de posicion por tick (breakeven/trailing), filtros de senal reforzados y filtro de noticias opcional via CSV."
#property description "v0.3: cierre parcial por R, entrada por puntuacion de confluencia, filtro de coste spread/SL y log de diagnostico en CSV."
#property description "v0.31/v0.32: comparacion robusta del spread en puntos y cierre parcial ligado a la hora de apertura (a prueba de cambio de ticket)."
#property description "v0.40: integracion real con el puente de IA local (veto/gestion/reporte), apagada y en modo sombra por defecto, autenticada por token."
#property description "v0.41: contexto de mercado en vivo para la IA (precio, indicadores recalculados y velas OHLC recientes M15/temporalidad superior en cada consulta)."
#property description "v0.42: gestion (MANAGE) de la IA asincrona por cola de archivos: ya no bloquea OnTick() esperando WebRequest."

// IMPORTANTE (leer antes de usar):
// - Ningun EA, por bueno que sea, puede garantizar ganancias ni evitar todas
//   las perdidas. Cualquiera que ofrezca eso miente. Este EA busca operar
//   con una ventaja estadistica razonable y un riesgo controlado, nada mas.
//   "Mejor precision" en esta version significa: senales mas selectivas,
//   salidas mas eficientes y menos coste de transaccion desperdiciado, NO
//   una promesa de mas ganancia garantizada.
// - MetaTrader 4 NO es una plataforma de alta frecuencia (HFT). OnTick() se
//   ejecuta con cada tick que el broker envia (tipicamente decenas a
//   cientos de milisegundos de latencia, a veces mas), sin ejecucion
//   co-localizada ni acceso a microestructura del order book. Ademas,
//   WebRequest() (usado por la integracion de IA) es una llamada
//   SINCRONA/bloqueante: mientras espera respuesta del puente, el EA (y en
//   la practica la terminal) se queda parado hasta AITimeoutMs. Por eso las
//   consultas de gestion a la IA estan limitadas a una vez cada
//   AIManageIntervalSeconds, no en cada tick.
// - AllowRealAccount=false bloquea cuentas reales por defecto.
// - El filtro de noticias (UseNewsFilter) NO descarga nada de internet: lee
//   un CSV local (MQL4/Files/<NewsFileName>) que el usuario debe mantener
//   actualizado manualmente o mediante un proceso externo. Si se activa y
//   el archivo falta o no se puede leer, el EA bloquea nuevas entradas por
//   seguridad (fail-safe), nunca al reves. Ver EA/README.md para el formato.
// - La integracion con el puente de IA local (EA/astur_ai_bridge.py) esta
//   implementada (UseLocalAI, AIShadowMode, WebRequest a /decision y
//   /outcome). Viene APAGADA (UseLocalAI=false) y, al activarla, arranca en
//   modo sombra (AIShadowMode=true): la IA solo analiza y registra, nunca
//   actua, hasta que se cambie explicitamente. La IA NUNCA puede abrir una
//   operacion, aumentar el lote ni retirar/alejar el SL; como mucho puede
//   vetar una entrada ya validada (BLOCK), acercar el SL con una formula
//   ATR fija (PROTECT, desactivado por defecto) o cerrar antes de tiempo
//   (CLOSE, desactivado por defecto). Con UseLocalAI=true es OBLIGATORIO
//   configurar AISharedSecret (debe coincidir con ASTUR_AI_SECRET del
//   puente) o el EA rechaza arrancar: sin ese token, cualquier proceso que
//   alcance el puerto del puente podria usarlo. Ver EA/ASTUR_AI_SETUP.md.
// - Ninguna mejora de este archivo esta validada con backtesting real: hay
//   que probarla en Strategy Tester (idealmente walk-forward) y despues en
//   una cuenta DEMO separada antes de considerar una cuenta real.
//   WebRequest() no funciona dentro del Strategy Tester, asi que la parte
//   de IA solo se puede probar en grafico real (demo primero).

input bool   AllowRealAccount       = false;
input bool   ResetRiskBaselines     = false;
input int    MagicNumber            = 26071601;

// Riesgo acordado
input double RiskPerTradePct        = 0.25;
input double MaxDailyLossPct        = 1.00;
input double MaxWeeklyLossPct       = 2.50;
input double MaxDrawdownPct         = 7.00;

// Filtros de ejecucion
input double MaxSpreadPips          = 1.50;
input double MaxSlippagePips        = 0.50;
input int    SessionStartHour       = 7;
input int    SessionEndHour         = 20;
input int    FridayLastEntryHour    = 16;
input int    MinimumBars            = 350;

// Senal base, deliberadamente simple para poder validarla sin sobreajuste
input int    FastEMAPeriod          = 20;
input int    SlowEMAPeriod          = 50;
input int    TrendEMAPeriod         = 200;
input int    ADXPeriod              = 14;
input double MinimumADX             = 20.0;
input int    ATRPeriod              = 14;
input double ATRStopMultiple        = 1.50;
input double RewardRiskRatio        = 1.50;
input double MinimumATRPips         = 2.00;
input double MaximumATRPips         = 20.00;
input double MaxSignalCandleATR     = 1.50;

// Filtros de confluencia (senal reforzada): cada uno suma un punto en vez
// de exigirse todos con un AND rigido. Se entra solo si el numero de
// aciertos alcanza MinimumConfluenceScore (de un maximo igual al numero de
// filtros activos). Esto es mas flexible y menos propenso a sobreajuste
// que encadenar condiciones obligatorias.
input bool             UseHigherTimeframeFilter = true;
input ENUM_TIMEFRAMES  HigherTimeframe          = PERIOD_H1;
input int              HigherTrendEMAPeriod     = 200;
input bool             UseTrendSlopeFilter      = true;
input bool             UseADXSlopeFilter        = true;
input int              MinimumConfluenceScore   = 2;

// Gestion de posicion abierta en cada tick (breakeven / trailing por ATR
// en vivo, y cierre parcial por multiplo del riesgo inicial de la orden)
input bool   UseBreakEven           = true;
input double BreakEvenTriggerATR    = 1.00;
input double BreakEvenLockPips      = 1.00;
input bool   UseTrailingStop        = true;
input double TrailingStartATR       = 1.50;
input double TrailingStepATR        = 1.00;
input double MinTrailingStepPips    = 0.50;
input bool   UsePartialClose        = true;
input double PartialCloseAtR        = 1.00;
input double PartialClosePct        = 50.00;

// Filtro de coste de transaccion: rechaza la entrada si el spread pesa
// demasiado sobre el stop loss planeado. Un SL ajustado con spread alto
// destruye la esperanza matematica aunque la senal en si sea buena.
input double MaxSpreadToSLRatio     = 0.20;

// Filtro de noticias opcional, basado en un CSV local (ver README)
input bool   UseNewsFilter          = false;
input string NewsFileName           = "ASTUR_News.csv";
input int    NewsBufferMinutesBefore= 30;
input int    NewsBufferMinutesAfter = 15;
input string NewsImpactFilter       = "HIGH";
input int    NewsReloadMinutes      = 60;

// Diagnostico: registra cada senal evaluada (tomada o no) en un CSV local
// para poder analizar fuera de MT4 (Excel/Python) que filtros aportan de
// verdad, en vez de adivinarlo.
input bool   UseDiagnosticsLog      = true;
input string DiagnosticsFileName    = "ASTUR_Diagnostics.csv";

// Integracion opcional con IA local (ver EA/ASTUR_AI_SETUP.md). Apagada por
// defecto; si se activa, arranca en modo sombra (solo observa). La IA nunca
// abre operaciones, nunca aumenta el lote, nunca retira ni aleja el SL.
// Requiere un token compartido (AISharedSecret) identico al ASTUR_AI_SECRET
// configurado en astur_ai_bridge.py: sin eso, el EA no arranca con
// UseLocalAI=true (para que SOLO tu, con el token, puedas usar el puente).
input bool   UseLocalAI              = false;
input bool   AIShadowMode            = true;
input bool   AIAllowEntryVeto        = true;
input bool   AIAllowProtectiveStop   = false;
input bool   AIAllowEarlyClose       = false;
input bool   AIFailClosed            = true;
input string AIBridgeURL             = "http://127.0.0.1:8765";
input string AISharedSecret          = "";
input int    AITimeoutMs             = 8000;
input int    AIManageIntervalSeconds = 20;
input double AIMinConfidence         = 0.55;
input double AIProtectATRMultiple    = 0.50;
input string AIDecisionsFileName     = "ASTUR_AI_Decisions.csv";
input string AIOutcomesFileName      = "ASTUR_TradeOutcomes.csv";

// Gestion (MANAGE) asincrona: WebRequest es sincrona/bloqueante en MQL4, asi
// que en vez de esperar la respuesta dentro de OnTick(), el EA escribe un
// archivo de peticion y sigue con su tick normal; un hilo del puente
// (astur_ai_bridge.py, ver ASTUR_AI_MQL4_FILES_DIR en .env.example) lo
// recoge, consulta el modelo con calma y escribe un archivo de respuesta.
// El EA solo comprueba en ticks posteriores si ya aparecio (FileIsExist es
// practicamente instantaneo), sin volver a bloquear la terminal. ENTRY
// sigue siendo sincrona (una vez por vela M15 cerrada, coste acotado).
input bool   UseAsyncManage          = true;
input string AIAsyncRequestFileName  = "ASTUR_AI_ManageRequest.json";
input string AIAsyncResponseFileName = "ASTUR_AI_ManageResponse.txt";
input int    AIAsyncTimeoutSec       = 45;

// Contexto de mercado en vivo enviado a la IA en cada consulta: precio
// actual, indicadores recalculados en el momento y series de velas OHLC
// recientes (M15 y la temporalidad superior), para que la IA razone sobre
// tendencia/momentum/estructura real del grafico, no solo sobre un par de
// valores sueltos. 0 desactiva el envio de esa serie de velas.
input int    AIContextCandlesM15     = 20;
input int    AIContextCandlesHTF     = 10;

datetime g_lastBarTime       = 0;
string   g_statePrefix       = "";
string   g_status            = "Inicializando";
bool     g_riskStopAnnounced = false;
string   g_lastKnownOrderKey = "";
datetime g_lastAIManageQuery = 0;

// Estado de la peticion MANAGE asincrona pendiente (a lo sumo una a la vez)
string   g_aiPendingRequestId = "";
string   g_aiPendingOrderKey  = "";
int      g_aiPendingTicket    = 0;
string   g_aiPendingSide      = "";
int      g_aiPendingScore     = -1;
datetime g_aiPendingSentAt    = 0;
int      g_aiRequestCounter   = 0;

struct AsturNewsEvent
  {
   datetime time;
   string   impact;
  };

AsturNewsEvent g_newsEvents[];
int            g_newsCount       = 0;
datetime       g_newsLastLoad    = 0;
bool           g_newsFileMissing = false;

struct AsturSignalContext
  {
   double fast1, fast2, slow1, slow2, trend1, trend2;
   double adx1, adx2, plus1, minus1;
   double atr1, atrPips;
   double open1, close1, candleRatio;
   int    crossDirection;   // 1 = cruce alcista, -1 = cruce bajista, 0 = sin cruce
   int    confluenceScore, confluenceMax;
   bool   htfOk, trendSlopeOk, adxSlopeOk;
   int    finalSignal;      // -1/0/1 tras todos los filtros de calidad
  };

//+------------------------------------------------------------------+
//| Inicializacion                                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_statePrefix = "ASTUR_" + IntegerToString(AccountNumber()) + "_" +
                   IntegerToString(MagicNumber) + "_";

   if(ResetRiskBaselines)
      DeleteRiskState();

   if(StringFind(Symbol(), "EURUSD", 0) < 0)
     {
      Print("ASTUR Safe EA: debe instalarse en un grafico EURUSD (se permiten sufijos del broker). Simbolo actual: ", Symbol());
      return(INIT_FAILED);
     }

   if(Period() != PERIOD_M15)
     {
      Print("ASTUR Safe EA: debe instalarse en EURUSD, periodo M15.");
      return(INIT_FAILED);
     }

   if(!InputsAreValid())
      return(INIT_PARAMETERS_INCORRECT);

   RefreshRiskState();
   g_lastBarTime = iTime(NULL, PERIOD_M15, 0);
   LoadNewsEvents();

   if(!IsDemo() && !AllowRealAccount)
      g_status = "BLOQUEADO EN REAL (AllowRealAccount=false)";
   else
      g_status = "Listo; esperando una senal cerrada";

   UpdateDashboard();
   Print("ASTUR Safe EA v0.42 iniciado. Cuenta=", AccountNumber(),
         ", modo=", (IsDemo() ? "DEMO" : "REAL"),
         ", simbolo=", Symbol(), ", periodo=M15",
         ", IA=", (UseLocalAI ? (AIShadowMode ? "sombra" : "activa") : "apagada"));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Limpieza                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Comment("");
  }

//+------------------------------------------------------------------+
//| Bucle principal: se despierta con cada tick recibido              |
//+------------------------------------------------------------------+
void OnTick()
  {
   RefreshRiskState();

   // Con el bloqueo de cuenta real activo, el EA no envia, modifica, cierra
   // ni elimina ninguna orden. El SL de una orden previa queda en el broker.
   if(!IsDemo() && !AllowRealAccount)
     {
      g_status = "BLOQUEADO EN REAL (AllowRealAccount=false)";
      UpdateDashboard();
      return;
     }

   string riskReason = "";
   if(RiskLimitBreached(riskReason))
     {
      g_status = "PARADA DE RIESGO: " + riskReason;
      if(!g_riskStopAnnounced)
        {
         Print("ASTUR Safe EA: parada de riesgo activada: ", riskReason);
         g_riskStopAnnounced = true;
        }
      if(CountEAOrders() > 0)
         CloseAllEAOrders(riskReason);
      UpdateDashboard();
      return;
     }
   g_riskStopAnnounced = false;

   // Gestion de la posicion abierta en cada tick (breakeven / trailing /
   // cierre parcial / consulta de gestion a la IA si esta activa), no solo
   // al cierre de vela: es la parte mas "en vivo" que MT4 permite.
   ManageOpenPosition();

   MaybeReloadNews();

   // Las entradas nuevas solo se evaluan al aparecer una vela M15 nueva,
   // usando exclusivamente velas cerradas.
   if(!IsNewBar())
     {
      UpdateDashboard();
      return;
     }

   AsturSignalContext ctx;
   BuildSignalContext(ctx);

   string blockReason = "";
   bool   canTrade = CanOpenNewTrade(blockReason);

   int    ticket = 0;
   double lots = 0.0, sl = 0.0, tp = 0.0;
   string tradeResult = "";

   if(ctx.finalSignal == 0)
     {
      g_status = "Sin senal valida en la ultima vela";
     }
   else if(!canTrade)
     {
      g_status = "Sin entrada: " + blockReason;
     }
   else
     {
      string aiVetoReason = "";
      if(UseLocalAI && AIAllowEntryVeto && AIEntryVeto(ctx, aiVetoReason))
        {
         g_status = "Sin entrada (veto IA): " + aiVetoReason;
         blockReason = "IA: " + aiVetoReason;
        }
      else
        {
         ExecuteSignal(ctx.finalSignal, ctx.confluenceScore, ticket, lots, sl, tp);
         tradeResult = (ticket > 0 ? "ABIERTO" : "FALLIDO");
         if(ticket <= 0)
            blockReason = g_status;
        }
     }

   LogSignalDiagnostic(ctx, blockReason, tradeResult, ticket, lots, sl, tp);
   UpdateDashboard();
  }

//+------------------------------------------------------------------+
//| Validacion de parametros                                          |
//+------------------------------------------------------------------+
bool InputsAreValid()
  {
   if(RiskPerTradePct <= 0.0 || RiskPerTradePct > 0.25)
     {
      Print("RiskPerTradePct debe ser > 0 y <= 0.25.");
      return(false);
     }

   if(MaxDailyLossPct <= 0.0 || MaxWeeklyLossPct <= 0.0 ||
      MaxDrawdownPct <= 0.0 || MaxDailyLossPct > MaxWeeklyLossPct ||
      MaxWeeklyLossPct > MaxDrawdownPct)
     {
      Print("Limites de perdida invalidos: diario <= semanal <= drawdown y todos > 0.");
      return(false);
     }

   if(FastEMAPeriod <= 1 || SlowEMAPeriod <= FastEMAPeriod ||
      TrendEMAPeriod <= SlowEMAPeriod || ADXPeriod <= 1 || ATRPeriod <= 1)
     {
      Print("Periodos de indicadores invalidos.");
      return(false);
     }

   if(ATRStopMultiple <= 0.0 || RewardRiskRatio <= 0.0 ||
      MinimumATRPips < 0.0 || MaximumATRPips <= MinimumATRPips ||
      MaxSpreadPips <= 0.0 || MaxSlippagePips < 0.0)
     {
      Print("Parametros de volatilidad, stop, beneficio o ejecucion invalidos.");
      return(false);
     }

   if(SessionStartHour < 0 || SessionStartHour > 23 ||
      SessionEndHour < 1 || SessionEndHour > 24 ||
      SessionStartHour >= SessionEndHour ||
      FridayLastEntryHour < 0 || FridayLastEntryHour > 23)
     {
      Print("Horario de trading invalido.");
      return(false);
     }

   if(UseHigherTimeframeFilter && (HigherTrendEMAPeriod <= 1 || HigherTimeframe <= PERIOD_M15))
     {
      Print("Filtro de temporalidad superior invalido: HigherTrendEMAPeriod debe ser > 1 y HigherTimeframe mayor que M15.");
      return(false);
     }

   if(MinimumConfluenceScore < 0 || MinimumConfluenceScore > 3)
     {
      Print("MinimumConfluenceScore debe estar entre 0 y 3.");
      return(false);
     }

   if(UseBreakEven && (BreakEvenTriggerATR <= 0.0 || BreakEvenLockPips < 0.0))
     {
      Print("Parametros de breakeven invalidos.");
      return(false);
     }

   if(UseTrailingStop && (TrailingStartATR <= 0.0 || TrailingStepATR <= 0.0 || MinTrailingStepPips < 0.0))
     {
      Print("Parametros de trailing stop invalidos.");
      return(false);
     }

   if(UsePartialClose && (PartialCloseAtR <= 0.0 || PartialClosePct <= 0.0 || PartialClosePct > 100.0))
     {
      Print("Parametros de cierre parcial invalidos.");
      return(false);
     }

   if(MaxSpreadToSLRatio <= 0.0 || MaxSpreadToSLRatio > 1.0)
     {
      Print("MaxSpreadToSLRatio debe estar entre 0 (excluido) y 1.");
      return(false);
     }

   if(UseNewsFilter && (NewsBufferMinutesBefore < 0 || NewsBufferMinutesAfter < 0 ||
      NewsReloadMinutes <= 0 || StringLen(NewsFileName) == 0))
     {
      Print("Parametros del filtro de noticias invalidos.");
      return(false);
     }

   if(UseDiagnosticsLog && StringLen(DiagnosticsFileName) == 0)
     {
      Print("DiagnosticsFileName no puede estar vacio si UseDiagnosticsLog esta activo.");
      return(false);
     }

   if(UseLocalAI)
     {
      if(StringLen(AIBridgeURL) == 0)
        {
         Print("AIBridgeURL no puede estar vacio si UseLocalAI esta activo.");
         return(false);
        }

      if(StringLen(AISharedSecret) == 0)
        {
         Print("AISharedSecret no puede estar vacio si UseLocalAI esta activo: sin un token compartido, ",
               "cualquier proceso que alcance el puerto del puente podria usarlo. Genera un token largo y ",
               "aleatorio, configuralo igual en el puente (variable de entorno ASTUR_AI_SECRET) y en este input.");
         return(false);
        }

      if(AITimeoutMs <= 0 || AIManageIntervalSeconds <= 0)
        {
         Print("AITimeoutMs y AIManageIntervalSeconds deben ser > 0.");
         return(false);
        }

      if(AIMinConfidence < 0.0 || AIMinConfidence > 1.0)
        {
         Print("AIMinConfidence debe estar entre 0 y 1.");
         return(false);
        }

      if(AIAllowProtectiveStop && AIProtectATRMultiple <= 0.0)
        {
         Print("AIProtectATRMultiple debe ser > 0 si AIAllowProtectiveStop esta activo.");
         return(false);
        }

      if(StringLen(AIDecisionsFileName) == 0 || StringLen(AIOutcomesFileName) == 0)
        {
         Print("AIDecisionsFileName y AIOutcomesFileName no pueden estar vacios si UseLocalAI esta activo.");
         return(false);
        }

      if(AIContextCandlesM15 < 0 || AIContextCandlesM15 > 200 ||
         AIContextCandlesHTF < 0 || AIContextCandlesHTF > 200)
        {
         Print("AIContextCandlesM15 y AIContextCandlesHTF deben estar entre 0 y 200.");
         return(false);
        }

      if(UseAsyncManage)
        {
         if(StringLen(AIAsyncRequestFileName) == 0 || StringLen(AIAsyncResponseFileName) == 0)
           {
            Print("AIAsyncRequestFileName y AIAsyncResponseFileName no pueden estar vacios si UseAsyncManage esta activo.");
            return(false);
           }
         if(AIAsyncTimeoutSec <= 0)
           {
            Print("AIAsyncTimeoutSec debe ser > 0.");
            return(false);
           }
        }
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Estado de riesgo persistente                                      |
//+------------------------------------------------------------------+
void DeleteRiskState()
  {
   GlobalVariableDel(g_statePrefix + "DAY_KEY");
   GlobalVariableDel(g_statePrefix + "DAY_EQ");
   GlobalVariableDel(g_statePrefix + "WEEK_KEY");
   GlobalVariableDel(g_statePrefix + "WEEK_EQ");
   GlobalVariableDel(g_statePrefix + "PEAK_EQ");
   GlobalVariablesFlush();
  }

void RefreshRiskState()
  {
   datetime now       = TimeCurrent();
   double   equity    = AccountEquity();
   int      dayKey    = (int)(now / 86400);
   int      daysBack  = (TimeDayOfWeek(now) + 6) % 7; // lunes=0
   int      weekKey   = (int)((now - daysBack * 86400) / 86400);

   string dayKeyName  = g_statePrefix + "DAY_KEY";
   string dayEqName   = g_statePrefix + "DAY_EQ";
   string weekKeyName = g_statePrefix + "WEEK_KEY";
   string weekEqName  = g_statePrefix + "WEEK_EQ";
   string peakEqName  = g_statePrefix + "PEAK_EQ";

   if(!GlobalVariableCheck(dayKeyName) ||
      (int)GlobalVariableGet(dayKeyName) != dayKey)
     {
      GlobalVariableSet(dayKeyName, dayKey);
      GlobalVariableSet(dayEqName, equity);
     }

   if(!GlobalVariableCheck(dayEqName))
      GlobalVariableSet(dayEqName, equity);

   if(!GlobalVariableCheck(weekKeyName) ||
      (int)GlobalVariableGet(weekKeyName) != weekKey)
     {
      GlobalVariableSet(weekKeyName, weekKey);
      GlobalVariableSet(weekEqName, equity);
     }

   if(!GlobalVariableCheck(weekEqName))
      GlobalVariableSet(weekEqName, equity);

   if(!GlobalVariableCheck(peakEqName))
      GlobalVariableSet(peakEqName, equity);
   else if(equity > GlobalVariableGet(peakEqName))
      GlobalVariableSet(peakEqName, equity);
  }

bool RiskLimitBreached(string &reason)
  {
   double equity    = AccountEquity();
   double dayStart  = GlobalVariableGet(g_statePrefix + "DAY_EQ");
   double weekStart = GlobalVariableGet(g_statePrefix + "WEEK_EQ");
   double peak      = GlobalVariableGet(g_statePrefix + "PEAK_EQ");

   if(dayStart > 0.0 && equity <= dayStart * (1.0 - MaxDailyLossPct / 100.0))
     {
      reason = "limite diario " + DoubleToString(MaxDailyLossPct, 2) + "%";
      return(true);
     }

   if(weekStart > 0.0 && equity <= weekStart * (1.0 - MaxWeeklyLossPct / 100.0))
     {
      reason = "limite semanal " + DoubleToString(MaxWeeklyLossPct, 2) + "%";
      return(true);
     }

   if(peak > 0.0 && equity <= peak * (1.0 - MaxDrawdownPct / 100.0))
     {
      reason = "drawdown maximo " + DoubleToString(MaxDrawdownPct, 2) + "%";
      return(true);
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Filtros antes de abrir                                            |
//+------------------------------------------------------------------+
bool CanOpenNewTrade(string &reason)
  {
   if(!IsConnected())
     {
      reason = "terminal sin conexion";
      return(false);
     }

   if(!IsTradeAllowed())
     {
      reason = "AutoTrading no permitido o contexto ocupado";
      return(false);
     }

   if(MarketInfo(Symbol(), MODE_TRADEALLOWED) <= 0.0)
     {
      reason = "simbolo no habilitado para operar";
      return(false);
     }

   if(iBars(NULL, PERIOD_M15) < MinimumBars)
     {
      reason = "historial M15 insuficiente";
      return(false);
     }

   if(CountEAOrders() > 0)
     {
      reason = "ya existe una operacion del EA";
      return(false);
     }

   datetime now = TimeCurrent();
   int weekDay  = TimeDayOfWeek(now);
   int hourNow  = TimeHour(now);

   if(weekDay == 0 || weekDay == 6)
     {
      reason = "fin de semana";
      return(false);
     }

   if(hourNow < SessionStartHour || hourNow >= SessionEndHour)
     {
      reason = "fuera del horario configurado (hora del broker)";
      return(false);
     }

   if(weekDay == 5 && hourNow >= FridayLastEntryHour)
     {
      reason = "bloqueo de nuevas entradas el viernes";
      return(false);
     }

   string newsReason = "";
   if(NewsBlackoutActive(newsReason))
     {
      reason = newsReason;
      return(false);
     }

   RefreshRates();
   int    spreadPoints = CurrentSpreadPoints();
   double spreadPips   = SpreadPointsToPips(spreadPoints);

   // MODE_SPREAD se expresa en puntos enteros. Compararlo en puntos evita
   // que 1.50 pips termine representado internamente como 1.500000000... y
   // sea rechazado por error cuando el limite tambien es 1.50.
   if(spreadPoints > PipsToPoints(MaxSpreadPips))
     {
      reason = "spread alto: " + DoubleToString(spreadPips, 2) + " pips";
      return(false);
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Construccion del contexto de senal sobre velas cerradas            |
//| Rellena TODOS los campos (incluso si no hay senal final) para que  |
//| el log de diagnostico pueda registrar cada evaluacion.             |
//+------------------------------------------------------------------+
void BuildSignalContext(AsturSignalContext &ctx)
  {
   ctx.fast1  = iMA(NULL, PERIOD_M15, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   ctx.fast2  = iMA(NULL, PERIOD_M15, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   ctx.slow1  = iMA(NULL, PERIOD_M15, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   ctx.slow2  = iMA(NULL, PERIOD_M15, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   ctx.trend1 = iMA(NULL, PERIOD_M15, TrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   ctx.trend2 = iMA(NULL, PERIOD_M15, TrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   ctx.adx1   = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1);
   ctx.adx2   = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 2);
   ctx.plus1  = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   ctx.minus1 = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   ctx.atr1   = iATR(NULL, PERIOD_M15, ATRPeriod, 1);
   ctx.open1  = iOpen(NULL, PERIOD_M15, 1);
   ctx.close1 = iClose(NULL, PERIOD_M15, 1);

   ctx.atrPips     = (ctx.atr1 > 0.0 ? ctx.atr1 / PipSize() : 0.0);
   ctx.candleRatio = (ctx.atr1 > 0.0 ? MathAbs(ctx.close1 - ctx.open1) / ctx.atr1 : 0.0);

   ctx.crossDirection = 0;
   if(ctx.fast2 <= ctx.slow2 && ctx.fast1 > ctx.slow1)
      ctx.crossDirection = 1;
   else if(ctx.fast2 >= ctx.slow2 && ctx.fast1 < ctx.slow1)
      ctx.crossDirection = -1;

   ctx.confluenceScore = 0;
   ctx.confluenceMax   = 0;
   ctx.htfOk           = true;
   ctx.trendSlopeOk    = true;
   ctx.adxSlopeOk      = true;
   ctx.finalSignal     = 0;

   // Filtros duros: si fallan, no hay senal, independientemente de la
   // puntuacion de confluencia (evitan operar sin volatilidad suficiente,
   // sobre una vela anomala, o directamente en contra de la tendencia).
   if(ctx.atr1 <= 0.0)
      return;
   if(ctx.atrPips < MinimumATRPips || ctx.atrPips > MaximumATRPips)
      return;
   if(ctx.candleRatio > MaxSignalCandleATR)
      return;
   if(ctx.crossDirection == 0)
      return;

   bool trendOk = (ctx.crossDirection > 0 ? ctx.close1 > ctx.trend1 : ctx.close1 < ctx.trend1);
   bool diOk    = (ctx.crossDirection > 0 ? ctx.plus1 > ctx.minus1 : ctx.minus1 > ctx.plus1);
   bool adxOk   = (ctx.adx1 >= MinimumADX);

   if(!trendOk || !diOk || !adxOk)
      return;

   // Filtros de confluencia (blandos): suman puntos en vez de bloquear
   // individualmente. Se exige un minimo, no la totalidad.
   if(UseHigherTimeframeFilter)
     {
      ctx.confluenceMax++;
      ctx.htfOk = HigherTimeframeAligned(ctx.crossDirection);
      if(ctx.htfOk)
         ctx.confluenceScore++;
     }

   if(UseTrendSlopeFilter)
     {
      ctx.confluenceMax++;
      ctx.trendSlopeOk = (ctx.crossDirection > 0 ? ctx.trend1 > ctx.trend2 : ctx.trend1 < ctx.trend2);
      if(ctx.trendSlopeOk)
         ctx.confluenceScore++;
     }

   if(UseADXSlopeFilter)
     {
      ctx.confluenceMax++;
      ctx.adxSlopeOk = (ctx.adx1 > ctx.adx2);
      if(ctx.adxSlopeOk)
         ctx.confluenceScore++;
     }

   if(ctx.confluenceMax > 0)
     {
      int required = MathMin(MinimumConfluenceScore, ctx.confluenceMax);
      if(ctx.confluenceScore < required)
         return;
     }

   ctx.finalSignal = ctx.crossDirection;
  }

//+------------------------------------------------------------------+
//| Confirmacion de tendencia en una temporalidad superior             |
//+------------------------------------------------------------------+
bool HigherTimeframeAligned(const int signal)
  {
   if(!UseHigherTimeframeFilter)
      return(true);

   if(iBars(NULL, HigherTimeframe) < HigherTrendEMAPeriod + 5)
      return(false);

   double htfClose = iClose(NULL, HigherTimeframe, 1);
   double htfTrend = iMA(NULL, HigherTimeframe, HigherTrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);

   if(htfTrend <= 0.0)
      return(false);

   if(signal > 0)
      return(htfClose > htfTrend);
   if(signal < 0)
      return(htfClose < htfTrend);
   return(false);
  }

//+------------------------------------------------------------------+
//| Envio de orden con SL/TP desde el primer momento                  |
//+------------------------------------------------------------------+
void ExecuteSignal(const int signal, const int confluenceScore,
                    int &outTicket, double &outLots, double &outSL, double &outTP)
  {
   outTicket = 0;
   outLots   = 0.0;
   outSL     = 0.0;
   outTP     = 0.0;

   RefreshRates();

   int    spreadPoints = CurrentSpreadPoints();
   double spreadPips   = SpreadPointsToPips(spreadPoints);
   if(spreadPoints > PipsToPoints(MaxSpreadPips))
     {
      g_status = "Orden cancelada: el spread cambio a " +
                 DoubleToString(spreadPips, 2) + " pips";
      return;
     }

   int    orderType    = (signal > 0 ? OP_BUY : OP_SELL);
   double entry        = (signal > 0 ? Ask : Bid);
   double atr          = iATR(NULL, PERIOD_M15, ATRPeriod, 1);
   double brokerMin    = (MarketInfo(Symbol(), MODE_STOPLEVEL) + 2.0) * Point;
   double stopDistance = MathMax(atr * ATRStopMultiple, brokerMin);
   double takeDistance = stopDistance * RewardRiskRatio;

   // Filtro de coste de transaccion: si el spread actual pesa demasiado
   // sobre el SL planeado, la esperanza matematica se deteriora aunque la
   // senal sea correcta. Mejor no operar que pagar un coste desproporcionado.
   double spreadPrice = spreadPoints * Point;
   double spreadToSL  = (stopDistance > 0.0 ? spreadPrice / stopDistance : 1.0);
   if(spreadToSL > MaxSpreadToSLRatio + 1.0e-8)
     {
      g_status = "Orden cancelada: spread demasiado alto respecto al SL (" +
                 DoubleToString(spreadToSL * 100.0, 1) + "% del riesgo)";
      return;
     }

   double stopLoss   = (signal > 0 ? entry - stopDistance : entry + stopDistance);
   double takeProfit = (signal > 0 ? entry + takeDistance : entry - takeDistance);

   stopLoss   = NormalizeDouble(stopLoss, Digits);
   takeProfit = NormalizeDouble(takeProfit, Digits);

   double lots = CalculateRiskLots(entry, stopLoss);
   if(lots <= 0.0)
     {
      g_status = "Orden cancelada: el lote minimo excede el riesgo permitido";
      Print("ASTUR Safe EA: no se abre la orden porque el lote calculado no es valido o el minimo del broker excede el riesgo.");
      return;
     }

   ResetLastError();
   double remainingMargin = AccountFreeMarginCheck(Symbol(), orderType, lots);
   int marginError = GetLastError();
   if(remainingMargin <= 0.0 || marginError == 134)
     {
      g_status = "Orden cancelada: margen libre insuficiente";
      Print("ASTUR Safe EA: margen insuficiente para ", DoubleToString(lots, LotDigits()), " lotes.");
      return;
     }

   int slippagePoints = PipsToPoints(MaxSlippagePips);
   color arrowColor   = (signal > 0 ? clrDodgerBlue : clrTomato);

   ResetLastError();
   int ticket = OrderSend(Symbol(), orderType, lots, entry, slippagePoints,
                          stopLoss, takeProfit, "ASTUR_SAFE_V0.42",
                          MagicNumber, 0, arrowColor);

   if(ticket < 0)
     {
      int errorCode = GetLastError();
      g_status = "OrderSend fallo; error " + IntegerToString(errorCode);
      Print("ASTUR Safe EA: OrderSend fallo. Error=", errorCode,
            ". No se reintenta sin SL/TP.");
      return;
     }

   if(!OrderSelect(ticket, SELECT_BY_TICKET) || OrderStopLoss() <= 0.0)
     {
      g_status = "ALERTA: orden sin SL verificable; cierre de emergencia";
      Print("ASTUR Safe EA: no se pudo verificar el SL del ticket ", ticket,
            ". Se intenta cerrar inmediatamente.");
      CloseTicketImmediately(ticket);
      return;
     }

   // Clave de estado basada en la HORA DE APERTURA, no en el ticket: algunos
   // brokers reasignan el numero de ticket al ejecutar un cierre parcial,
   // pero la hora de apertura de la operacion no cambia. Usarla como clave
   // garantiza que el cierre parcial (ver ManageOpenPosition) se ejecute
   // como mucho una vez por operacion, pase lo que pase con el ticket.
   string orderKey = IntegerToString((int)OrderOpenTime());
   GlobalVariableSet(g_statePrefix + "RISK_" + orderKey, stopDistance);
   GlobalVariableSet(g_statePrefix + "PARTIAL_" + orderKey, 0);
   GlobalVariableSet(g_statePrefix + "SCORE_" + orderKey, confluenceScore);

   outTicket = ticket;
   outLots   = lots;
   outSL     = stopLoss;
   outTP     = takeProfit;

   g_status = "Operacion abierta; ticket " + IntegerToString(ticket);
   Print("ASTUR Safe EA: ticket=", ticket,
         ", lado=", (signal > 0 ? "BUY" : "SELL"),
         ", lotes=", DoubleToString(lots, LotDigits()),
         ", SL=", DoubleToString(stopLoss, Digits),
         ", TP=", DoubleToString(takeProfit, Digits));
  }

//+------------------------------------------------------------------+
//| Tamano de lote por perdida maxima hasta el SL                     |
//+------------------------------------------------------------------+
double CalculateRiskLots(const double entry, const double stopLoss)
  {
   double riskMoney = AccountEquity() * RiskPerTradePct / 100.0;
   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   double minLot    = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot    = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep   = MarketInfo(Symbol(), MODE_LOTSTEP);

   if(tickSize <= 0.0)
      tickSize = Point;
   if(tickValue <= 0.0 || lotStep <= 0.0 || minLot <= 0.0)
      return(0.0);

   double riskPerLot = (MathAbs(entry - stopLoss) / tickSize) * tickValue;
   if(riskPerLot <= 0.0)
      return(0.0);

   double rawLots = riskMoney / riskPerLot;
   double lots    = MathFloor(rawLots / lotStep + 1e-8) * lotStep;
   lots           = MathMin(lots, maxLot);
   lots           = NormalizeDouble(lots, LotDigits());

   // Nunca se fuerza el lote minimo si con ello se supera el riesgo fijado.
   if(lots < minLot)
      return(0.0);

   return(lots);
  }

//+------------------------------------------------------------------+
//| Gestion de la (unica) posicion abierta en cada tick:               |
//| cierre parcial por R, breakeven / trailing por ATR en vivo, y      |
//| gestion adicional de la IA si esta activa (PROTECT/CLOSE).         |
//| El SL solo se mueve para reducir riesgo, nunca para aumentarlo.    |
//| El estado se indexa por la hora de apertura de la operacion, no    |
//| por el ticket (ver ExecuteSignal), y tras un cierre parcial se     |
//| relocaliza la orden por posicion en vez de asumir que el ticket    |
//| sigue siendo el mismo.                                             |
//+------------------------------------------------------------------+
void ManageOpenPosition()
  {
   int      openTicket    = 0;
   int      openType      = -1;
   datetime openTimeFound = 0;

   for(int pos = OrdersTotal() - 1; pos >= 0; pos--)
     {
      if(!OrderSelect(pos, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
         continue;
      int type = OrderType();
      if(type != OP_BUY && type != OP_SELL)
         continue;
      openTicket    = OrderTicket();
      openType      = type;
      openTimeFound = OrderOpenTime();
      break; // el EA nunca mantiene mas de una operacion a la vez
     }

   if(openTicket == 0)
     {
      if(g_lastKnownOrderKey != "")
        {
         ReportTradeOutcome(g_lastKnownOrderKey);
         g_lastKnownOrderKey = "";
        }
      return;
     }

   string orderKey = IntegerToString((int)openTimeFound);
   if(g_lastKnownOrderKey != orderKey)
     {
      g_lastKnownOrderKey = orderKey;
      g_lastAIManageQuery = 0; // primera consulta de IA pronta para la operacion nueva
     }

   if(!UseBreakEven && !UseTrailingStop && !UsePartialClose && !UseLocalAI)
      return;

   double atr = iATR(NULL, PERIOD_M15, ATRPeriod, 0);
   if(atr <= 0.0)
      return;

   RefreshRates();

   double openPrice = OrderOpenPrice();
   double currentSL = OrderStopLoss();
   double lots      = OrderLots();

   string riskVarName    = g_statePrefix + "RISK_" + orderKey;
   string partialVarName = g_statePrefix + "PARTIAL_" + orderKey;
   double initialRisk = GlobalVariableCheck(riskVarName) ? GlobalVariableGet(riskVarName) : 0.0;
   if(initialRisk <= 0.0)
      initialRisk = MathAbs(openPrice - currentSL); // respaldo si el estado no esta disponible

   bool partialCloseAttempted = false;

   if(UsePartialClose && initialRisk > 0.0 &&
      (!GlobalVariableCheck(partialVarName) || GlobalVariableGet(partialVarName) < 1.0))
     {
      double profitNow = (openType == OP_BUY ? Bid - openPrice : openPrice - Ask);
      if(profitNow >= PartialCloseAtR * initialRisk)
        {
         double minLot  = MarketInfo(Symbol(), MODE_MINLOT);
         double lotStep = MarketInfo(Symbol(), MODE_LOTSTEP);

         double closeLots = MathFloor((lots * PartialClosePct / 100.0) / lotStep + 1e-8) * lotStep;
         closeLots = NormalizeDouble(closeLots, LotDigits());

         bool fullClose = (closeLots >= lots - lotStep * 0.5);
         if(fullClose)
            closeLots = NormalizeDouble(lots, LotDigits());

         double remainder = NormalizeDouble(lots - closeLots, LotDigits());

         if(closeLots >= minLot && (fullClose || remainder >= minLot))
           {
            partialCloseAttempted = true;
            double closePrice = (openType == OP_BUY ? Bid : Ask);
            ResetLastError();
            if(OrderClose(openTicket, closeLots, closePrice, PipsToPoints(MaxSlippagePips), clrLime))
              {
               GlobalVariableSet(partialVarName, 1);
               Print("ASTUR Safe EA: cierre parcial ejecutado. ticket=", openTicket,
                     ", lotes cerrados=", DoubleToString(closeLots, LotDigits()));
              }
            else
               Print("ASTUR Safe EA: cierre parcial fallo. ticket=", openTicket,
                     ". Error=", GetLastError());
           }
         else
            GlobalVariableSet(partialVarName, 1); // lote demasiado pequeno para partir; no reintentar cada tick
        }
     }

   // Si se intento un cierre parcial, el ticket pudo haber cambiado (segun
   // el broker) o la orden pudo cerrarse del todo: relocalizar por posicion
   // (magic+simbolo), no confiar en que "openTicket" siga siendo valido.
   if(partialCloseAttempted)
     {
      bool stillOpen = false;
      for(int pos2 = OrdersTotal() - 1; pos2 >= 0; pos2--)
        {
         if(!OrderSelect(pos2, SELECT_BY_POS, MODE_TRADES))
            continue;
         if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
            continue;
         int type2 = OrderType();
         if(type2 != OP_BUY && type2 != OP_SELL)
            continue;
         stillOpen  = true;
         openTicket = OrderTicket();
         openType   = type2;
         break;
        }

      if(!stillOpen)
         return; // el cierre parcial fue en realidad un cierre total; el outcome se reporta en el siguiente tick
     }
   else
     {
      if(!OrderSelect(openTicket, SELECT_BY_TICKET))
         return;
     }

   currentSL = OrderStopLoss();
   double takeProfit = OrderTakeProfit();
   openPrice = OrderOpenPrice();

   double minLockDist  = (MarketInfo(Symbol(), MODE_STOPLEVEL) + 2.0) * Point;
   double minStepPrice = MathMax(MinTrailingStepPips * PipSize(), Point);
   double candidateSL  = currentSL;
   bool   deterministicModify = false;

   if(openType == OP_BUY)
     {
      double profit = Bid - openPrice;

      if(UseBreakEven && profit >= BreakEvenTriggerATR * atr)
         candidateSL = MathMax(candidateSL, openPrice + BreakEvenLockPips * PipSize());

      if(UseTrailingStop && profit >= TrailingStartATR * atr)
         candidateSL = MathMax(candidateSL, Bid - TrailingStepATR * atr);

      candidateSL = MathMin(candidateSL, Bid - minLockDist);
      deterministicModify = (candidateSL - currentSL >= minStepPrice);
     }
   else
     {
      double profit = openPrice - Ask;

      if(UseBreakEven && profit >= BreakEvenTriggerATR * atr)
         candidateSL = MathMin(candidateSL, openPrice - BreakEvenLockPips * PipSize());

      if(UseTrailingStop && profit >= TrailingStartATR * atr)
         candidateSL = MathMin(candidateSL, Ask + TrailingStepATR * atr);

      candidateSL = MathMax(candidateSL, Ask + minLockDist);
      deterministicModify = (currentSL - candidateSL >= minStepPrice);
     }

   if(deterministicModify)
     {
      candidateSL = NormalizeDouble(candidateSL, Digits);

      ResetLastError();
      if(!OrderModify(openTicket, openPrice, candidateSL, takeProfit, 0, clrYellow))
         Print("ASTUR Safe EA: OrderModify (breakeven/trailing) fallo ticket=", openTicket,
               ". Error=", GetLastError());
      else
         Print("ASTUR Safe EA: SL protegido actualizado. ticket=", openTicket,
               ", nuevoSL=", DoubleToString(candidateSL, Digits));
     }

   AIManageCheck(openTicket, openType, orderKey);
  }

void CleanupOrderState(const string orderKey)
  {
   if(orderKey == "")
      return;
   GlobalVariableDel(g_statePrefix + "RISK_" + orderKey);
   GlobalVariableDel(g_statePrefix + "PARTIAL_" + orderKey);
   GlobalVariableDel(g_statePrefix + "SCORE_" + orderKey);
  }

//+------------------------------------------------------------------+
//| Cierre de emergencia: solo operaciones de este EA                 |
//+------------------------------------------------------------------+
void CloseAllEAOrders(const string reason)
  {
   for(int pos = OrdersTotal() - 1; pos >= 0; pos--)
     {
      if(!OrderSelect(pos, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
         continue;

      int ticket = OrderTicket();
      int type   = OrderType();

      if(type == OP_BUY || type == OP_SELL)
         CloseTicketImmediately(ticket);
      else
        {
         ResetLastError();
         if(!OrderDelete(ticket, clrNONE))
            Print("ASTUR Safe EA: no se pudo borrar pendiente ", ticket,
                  ". Error=", GetLastError());
        }
     }

   Print("ASTUR Safe EA: proteccion activada: ", reason,
         ". No se tocan operaciones con otro MagicNumber.");
  }

bool CloseTicketImmediately(const int ticket)
  {
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(!OrderSelect(ticket, SELECT_BY_TICKET))
         return(false);

      int type = OrderType();
      if(type != OP_BUY && type != OP_SELL)
         return(false);

      RefreshRates();
      double closePrice = (type == OP_BUY ? Bid : Ask);

      ResetLastError();
      if(OrderClose(ticket, OrderLots(), closePrice,
                    PipsToPoints(MaxSlippagePips), clrRed))
         return(true);

      int errorCode = GetLastError();
      Print("ASTUR Safe EA: intento ", attempt + 1,
            " de cierre fallo para ticket ", ticket,
            ". Error=", errorCode);
      Sleep(100);
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Filtro de noticias basado en CSV local                            |
//| Formato por linea: YYYY.MM.DD,HH:MM,IMPACTO  (hora del broker)    |
//+------------------------------------------------------------------+
void LoadNewsEvents()
  {
   g_newsCount = 0;
   ArrayResize(g_newsEvents, 0);
   g_newsFileMissing = false;

   if(!UseNewsFilter)
     {
      g_newsLastLoad = TimeCurrent();
      return;
     }

   if(!FileIsExist(NewsFileName))
     {
      g_newsFileMissing = true;
      g_newsLastLoad = TimeCurrent();
      Print("ASTUR Safe EA: filtro de noticias activo pero no se encontro ", NewsFileName,
            " en MQL4/Files. No se abriran operaciones nuevas hasta corregirlo (fail-safe).");
      return;
     }

   int handle = FileOpen(NewsFileName, FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
     {
      g_newsFileMissing = true;
      g_newsLastLoad = TimeCurrent();
      Print("ASTUR Safe EA: no se pudo abrir ", NewsFileName, ". Error=", GetLastError());
      return;
     }

   int count = 0;
   while(!FileIsEnding(handle) && count < 500)
     {
      string dateStr = FileReadString(handle);
      if(StringLen(dateStr) == 0)
         break;
      string timeStr   = FileReadString(handle);
      string impactStr = FileReadString(handle);

      datetime eventTime = StringToTime(dateStr + " " + timeStr);
      if(eventTime > 0)
        {
         ArrayResize(g_newsEvents, count + 1);
         g_newsEvents[count].time   = eventTime;
         g_newsEvents[count].impact = impactStr;
         count++;
        }
     }

   FileClose(handle);
   g_newsCount    = count;
   g_newsLastLoad = TimeCurrent();
   Print("ASTUR Safe EA: filtro de noticias: ", g_newsCount, " eventos cargados desde ", NewsFileName);
  }

void MaybeReloadNews()
  {
   if(!UseNewsFilter)
      return;
   if(g_newsLastLoad == 0 || (TimeCurrent() - g_newsLastLoad) >= NewsReloadMinutes * 60)
      LoadNewsEvents();
  }

bool NewsBlackoutActive(string &reason)
  {
   if(!UseNewsFilter)
      return(false);

   if(g_newsFileMissing)
     {
      reason = "filtro de noticias activo sin archivo valido (" + NewsFileName + ")";
      return(true);
     }

   string filterUpper = NewsImpactFilter;
   StringToUpper(filterUpper);

   datetime now = TimeCurrent();
   for(int i = 0; i < g_newsCount; i++)
     {
      string impactUpper = g_newsEvents[i].impact;
      StringToUpper(impactUpper);
      if(StringFind(filterUpper, impactUpper, 0) < 0)
         continue;

      datetime windowStart = g_newsEvents[i].time - NewsBufferMinutesBefore * 60;
      datetime windowEnd   = g_newsEvents[i].time + NewsBufferMinutesAfter * 60;

      if(now >= windowStart && now <= windowEnd)
        {
         reason = "ventana de noticias (" + g_newsEvents[i].impact + ") " +
                  TimeToString(g_newsEvents[i].time, TIME_DATE | TIME_MINUTES);
         return(true);
        }
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Integracion con IA local (opcional, apagada por defecto)          |
//| La IA SOLO puede: vetar una entrada ya validada (BLOCK), acercar  |
//| el SL con una formula ATR fija (PROTECT) o cerrar antes de tiempo |
//| (CLOSE, desactivado por defecto). Nunca abre operaciones, nunca   |
//| aumenta el lote, nunca retira ni aleja el SL. En AIShadowMode     |
//| (por defecto) solo registra su opinion, nunca actua. Requiere     |
//| AISharedSecret (token compartido con el puente) para funcionar.   |
//+------------------------------------------------------------------+
bool CallAIBridge(const string path, const string jsonBody, string &responseText)
  {
   responseText = "";
   if(!UseLocalAI)
      return(false);

   string url     = AIBridgeURL + path;
   string headers = "Content-Type: application/json\r\n";
   if(StringLen(AISharedSecret) > 0)
      headers += "X-ASTUR-Token: " + AISharedSecret + "\r\n";

   uchar postData[];
   int len = StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(len < 0)
      len = 0;
   ArrayResize(postData, len);

   uchar  result[];
   string resultHeaders;

   ResetLastError();
   int status = WebRequest("POST", url, headers, AITimeoutMs, postData, result, resultHeaders);

   if(status == -1)
     {
      int err = GetLastError();
      Print("ASTUR IA: WebRequest fallo. Error=", err,
            err == 4060 ? (" (URL no autorizada; agregar " + AIBridgeURL +
                            " en Herramientas > Opciones > Asesores Expertos)") : "");
      return(false);
     }

   responseText = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);

   if(status == 401)
     {
      Print("ASTUR IA: el puente rechazo la peticion (401 no autorizado). Revisa que AISharedSecret ",
            "coincida exactamente con ASTUR_AI_SECRET configurado en astur_ai_bridge.py.");
      return(false);
     }

   if(status != 200)
     {
      Print("ASTUR IA: respuesta HTTP ", status, ": ", responseText);
      return(false);
     }

   return(true);
  }

bool ParseAIDecision(const string responseText, string &action, double &confidence, string &reason)
  {
   string parts[];
   int n = StringSplit(responseText, '|', parts);
   if(n < 3)
     {
      action     = "";
      confidence = 0.0;
      reason     = "respuesta invalida";
      return(false);
     }

   action     = parts[0];
   confidence = StringToDouble(parts[1]);
   reason     = parts[2];
   for(int i = 3; i < n; i++)
      reason += "|" + parts[i];

   return(true);
  }

void LogAIDecision(const string event, const int ticket, const string side, const int score,
                    const string action, const double confidence, const string reason)
  {
   string line = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "," +
                 event + "," +
                 IntegerToString(ticket) + "," +
                 side + "," +
                 IntegerToString(score) + "," +
                 action + "," +
                 DoubleToString(confidence, 4) + "," +
                 CsvSafe(reason) + "," +
                 (AIShadowMode ? "SOMBRA" : "ACTIVO");

   AppendToCsv(AIDecisionsFileName,
      "Timestamp,Evento,Ticket,Side,Score,Accion,Confianza,Motivo,Modo",
      line);
  }

//+------------------------------------------------------------------+
//| Serie de velas OHLC en JSON (de la mas antigua a la mas reciente,  |
//| solo velas CERRADAS) para que la IA vea movimiento real reciente,  |
//| no solo un indicador puntual.                                      |
//+------------------------------------------------------------------+
string BuildCandlesJson(const int timeframe, const int count)
  {
   if(count <= 0)
      return("[]");

   int available = iBars(NULL, timeframe);
   int n = MathMin(count, available);
   if(n <= 0)
      return("[]");

   string json = "[";
   for(int i = n; i >= 1; i--)
     {
      if(i < n)
         json += ",";
      json += "{" +
              "\"t\":\"" + TimeToString(iTime(NULL, timeframe, i), TIME_DATE | TIME_MINUTES) + "\"," +
              "\"o\":" + DoubleToString(iOpen(NULL, timeframe, i), Digits) + "," +
              "\"h\":" + DoubleToString(iHigh(NULL, timeframe, i), Digits) + "," +
              "\"l\":" + DoubleToString(iLow(NULL, timeframe, i), Digits) + "," +
              "\"c\":" + DoubleToString(iClose(NULL, timeframe, i), Digits) +
              "}";
     }
   json += "]";
   return(json);
  }

//+------------------------------------------------------------------+
//| Snapshot de mercado EN VIVO (recalculado en el momento de cada     |
//| consulta): precio actual, indicadores frescos y las series de      |
//| velas M15/temporalidad superior. Se reutiliza tanto para ENTRY     |
//| como para MANAGE, para que la IA siempre razone sobre datos         |
//| actuales del grafico, no sobre lo que habia al abrir la operacion. |
//+------------------------------------------------------------------+
string BuildMarketSnapshotJson()
  {
   double fast1  = iMA(NULL, PERIOD_M15, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double slow1  = iMA(NULL, PERIOD_M15, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double trend1 = iMA(NULL, PERIOD_M15, TrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double adx1   = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1);
   double plus1  = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   double minus1 = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   double atr1   = iATR(NULL, PERIOD_M15, ATRPeriod, 1);
   double atrPips = (atr1 > 0.0 ? atr1 / PipSize() : 0.0);

   RefreshRates();

   return("\"market\":{" +
          "\"symbol\":\"" + Symbol() + "\"," +
          "\"bid\":" + DoubleToString(Bid, Digits) + "," +
          "\"ask\":" + DoubleToString(Ask, Digits) + "," +
          "\"spread_pips\":" + DoubleToString(SpreadPointsToPips(CurrentSpreadPoints()), 2) + "," +
          "\"ema_fast\":" + DoubleToString(fast1, Digits) + "," +
          "\"ema_slow\":" + DoubleToString(slow1, Digits) + "," +
          "\"ema_trend\":" + DoubleToString(trend1, Digits) + "," +
          "\"adx\":" + DoubleToString(adx1, 2) + "," +
          "\"di_plus\":" + DoubleToString(plus1, 2) + "," +
          "\"di_minus\":" + DoubleToString(minus1, 2) + "," +
          "\"atr_pips\":" + DoubleToString(atrPips, 2) + "," +
          "\"weekday\":" + IntegerToString(TimeDayOfWeek(TimeCurrent())) + "," +
          "\"hour\":" + IntegerToString(TimeHour(TimeCurrent())) + "," +
          "\"current_bar_m15\":{" +
             "\"o\":" + DoubleToString(iOpen(NULL, PERIOD_M15, 0), Digits) + "," +
             "\"h\":" + DoubleToString(iHigh(NULL, PERIOD_M15, 0), Digits) + "," +
             "\"l\":" + DoubleToString(iLow(NULL, PERIOD_M15, 0), Digits) + "," +
             "\"c\":" + DoubleToString(iClose(NULL, PERIOD_M15, 0), Digits) +
          "}," +
          "\"candles_m15\":" + BuildCandlesJson(PERIOD_M15, AIContextCandlesM15) + "," +
          "\"candles_htf\":" + BuildCandlesJson(HigherTimeframe, AIContextCandlesHTF) +
          "}");
  }

bool AIEntryVeto(const AsturSignalContext &ctx, string &reason)
  {
   reason = "";

   string side = (ctx.finalSignal > 0 ? "BUY" : "SELL");
   string json = "{" +
                 "\"event\":\"ENTRY\"," +
                 "\"side\":\"" + side + "\"," +
                 "\"score\":" + IntegerToString(ctx.confluenceScore) + "," +
                 "\"score_max\":" + IntegerToString(ctx.confluenceMax) + "," +
                 "\"htf_ok\":" + (ctx.htfOk ? "true" : "false") + "," +
                 "\"trend_slope_ok\":" + (ctx.trendSlopeOk ? "true" : "false") + "," +
                 "\"adx_slope_ok\":" + (ctx.adxSlopeOk ? "true" : "false") + "," +
                 BuildMarketSnapshotJson() +
                 "}";

   string response;
   bool ok = CallAIBridge("/decision", json, response);

   if(!ok)
     {
      LogAIDecision("ENTRY", 0, side, ctx.confluenceScore, "SIN_RESPUESTA", 0.0, "bridge no disponible");
      if(AIShadowMode)
         return(false);
      if(AIFailClosed)
        {
         reason = "IA sin respuesta (fail-closed)";
         return(true);
        }
      return(false);
     }

   string action = "", decisionReason = "";
   double confidence = 0.0;
   ParseAIDecision(response, action, confidence, decisionReason);
   LogAIDecision("ENTRY", 0, side, ctx.confluenceScore, action, confidence, decisionReason);

   if(AIShadowMode)
      return(false); // modo sombra: se registra el consejo, nunca actua

   if(action == "BLOCK" && confidence >= AIMinConfidence)
     {
      reason = decisionReason;
      return(true);
     }

   return(false);
  }

void ApplyAIProtect(const int ticket, const int type)
  {
   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return;

   double atr = iATR(NULL, PERIOD_M15, ATRPeriod, 0);
   if(atr <= 0.0)
      return;

   RefreshRates();

   double currentSL   = OrderStopLoss();
   double openPrice   = OrderOpenPrice();
   double takeProfit  = OrderTakeProfit();
   double minLockDist = (MarketInfo(Symbol(), MODE_STOPLEVEL) + 2.0) * Point;
   double candidateSL = currentSL;

   if(type == OP_BUY)
     {
      candidateSL = MathMax(candidateSL, Bid - AIProtectATRMultiple * atr);
      candidateSL = MathMin(candidateSL, Bid - minLockDist);
      if(candidateSL <= currentSL)
         return; // la IA solo puede acercar el SL, nunca alejarlo
     }
   else
     {
      candidateSL = MathMin(candidateSL, Ask + AIProtectATRMultiple * atr);
      candidateSL = MathMax(candidateSL, Ask + minLockDist);
      if(candidateSL >= currentSL)
         return;
     }

   candidateSL = NormalizeDouble(candidateSL, Digits);

   ResetLastError();
   if(!OrderModify(ticket, openPrice, candidateSL, takeProfit, 0, clrOrange))
      Print("ASTUR IA: PROTECT fallo ticket=", ticket, ". Error=", GetLastError());
   else
      Print("ASTUR IA: PROTECT aplicado. ticket=", ticket, ", nuevoSL=", DoubleToString(candidateSL, Digits));
  }

void AIManageCheck(const int ticket, const int type, const string orderKey)
  {
   if(!UseLocalAI)
      return;

   if(UseAsyncManage)
      AIManageCheckAsync(ticket, type, orderKey);
   else
      AIManageCheckSync(ticket, type, orderKey);
  }

//+------------------------------------------------------------------+
//| Variante sincrona (bloqueante): la conserva UseAsyncManage=false   |
//| como via de respaldo/depuracion. WebRequest pausa el EA hasta      |
//| AITimeoutMs mientras espera respuesta.                             |
//+------------------------------------------------------------------+
void AIManageCheckSync(const int ticket, const int type, const string orderKey)
  {
   if(TimeCurrent() - g_lastAIManageQuery < AIManageIntervalSeconds)
      return;
   g_lastAIManageQuery = TimeCurrent();

   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return;

   double   openPrice = OrderOpenPrice();
   datetime openTime  = OrderOpenTime();
   double   atr       = iATR(NULL, PERIOD_M15, ATRPeriod, 0);
   if(atr <= 0.0)
      return;

   RefreshRates();

   double riskValue = GlobalVariableCheck(g_statePrefix + "RISK_" + orderKey) ?
                       GlobalVariableGet(g_statePrefix + "RISK_" + orderKey) : 0.0;
   double profitPrice  = (type == OP_BUY ? Bid - openPrice : openPrice - Ask);
   double profitR      = (riskValue > 0.0 ? profitPrice / riskValue : 0.0);
   int    scoreAtEntry = GlobalVariableCheck(g_statePrefix + "SCORE_" + orderKey) ?
                          (int)GlobalVariableGet(g_statePrefix + "SCORE_" + orderKey) : -1;
   string side = (type == OP_BUY ? "BUY" : "SELL");

   string json = "{" +
                 "\"event\":\"MANAGE\"," +
                 "\"ticket\":" + IntegerToString(ticket) + "," +
                 "\"side\":\"" + side + "\"," +
                 "\"score\":" + IntegerToString(scoreAtEntry) + "," +
                 "\"profit_r\":" + DoubleToString(profitR, 2) + "," +
                 "\"minutes_open\":" + IntegerToString((int)((TimeCurrent() - openTime) / 60)) + "," +
                 BuildMarketSnapshotJson() +
                 "}";

   string response;
   bool ok = CallAIBridge("/decision", json, response);

   if(!ok)
     {
      LogAIDecision("MANAGE", ticket, side, scoreAtEntry, "SIN_RESPUESTA", 0.0, "bridge no disponible");
      return; // sin respuesta: nunca fuerza nada, solo se pierde esta capa extra
     }

   string action = "", reason = "";
   double confidence = 0.0;
   ParseAIDecision(response, action, confidence, reason);
   LogAIDecision("MANAGE", ticket, side, scoreAtEntry, action, confidence, reason);

   if(AIShadowMode)
      return; // solo registra, nunca actua

   if(confidence < AIMinConfidence)
      return;

   if(action == "PROTECT" && AIAllowProtectiveStop)
      ApplyAIProtect(ticket, type);
   else if(action == "CLOSE" && AIAllowEarlyClose)
      CloseTicketImmediately(ticket);
  }

//+------------------------------------------------------------------+
//| Variante asincrona (recomendada): NUNCA bloquea OnTick(). Escribe  |
//| un archivo de peticion y sigue; en ticks posteriores comprueba,    |
//| con una simple lectura de archivo (instantanea), si ya hay         |
//| respuesta. La espera real por el modelo queda repartida entre      |
//| varios ticks en vez de congelar uno solo.                          |
//+------------------------------------------------------------------+
void AIManageCheckAsync(const int ticket, const int type, const string orderKey)
  {
   // Si la operacion sobre la que se pregunto ya no es la actual (cerro,
   // cambio de ticket por un cierre parcial, etc.), descarta cualquier
   // peticion pendiente: no tiene sentido actuar sobre una orden distinta.
   if(g_aiPendingRequestId != "" && g_aiPendingOrderKey != orderKey)
     {
      g_aiPendingRequestId = "";
      g_aiPendingOrderKey  = "";
     }

   if(g_aiPendingRequestId != "")
     {
      AIManageCheckPollResponse(type);
      return;
     }

   if(TimeCurrent() - g_lastAIManageQuery < AIManageIntervalSeconds)
      return;
   g_lastAIManageQuery = TimeCurrent();

   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return;

   double   openPrice = OrderOpenPrice();
   datetime openTime  = OrderOpenTime();
   double   atr       = iATR(NULL, PERIOD_M15, ATRPeriod, 0);
   if(atr <= 0.0)
      return;

   RefreshRates();

   double riskValue = GlobalVariableCheck(g_statePrefix + "RISK_" + orderKey) ?
                       GlobalVariableGet(g_statePrefix + "RISK_" + orderKey) : 0.0;
   double profitPrice  = (type == OP_BUY ? Bid - openPrice : openPrice - Ask);
   double profitR      = (riskValue > 0.0 ? profitPrice / riskValue : 0.0);
   int    scoreAtEntry = GlobalVariableCheck(g_statePrefix + "SCORE_" + orderKey) ?
                          (int)GlobalVariableGet(g_statePrefix + "SCORE_" + orderKey) : -1;
   string side = (type == OP_BUY ? "BUY" : "SELL");

   g_aiRequestCounter++;
   string requestId = orderKey + "_" + IntegerToString(g_aiRequestCounter) + "_" + IntegerToString((int)TimeCurrent());

   string json = "{" +
                 "\"request_id\":\"" + requestId + "\"," +
                 "\"event\":\"MANAGE\"," +
                 "\"ticket\":" + IntegerToString(ticket) + "," +
                 "\"side\":\"" + side + "\"," +
                 "\"score\":" + IntegerToString(scoreAtEntry) + "," +
                 "\"profit_r\":" + DoubleToString(profitR, 2) + "," +
                 "\"minutes_open\":" + IntegerToString((int)((TimeCurrent() - openTime) / 60)) + "," +
                 BuildMarketSnapshotJson() +
                 "}";

   // Se limpia cualquier respuesta vieja antes de lanzar la peticion nueva,
   // para que nunca se pueda leer por error una respuesta de un ciclo
   // anterior (el request_id ya protege contra esto, pero asi ni siquiera
   // se llega a comparar).
   if(FileIsExist(AIAsyncResponseFileName))
      FileDelete(AIAsyncResponseFileName);

   if(WriteAIRequestFile(json))
     {
      g_aiPendingRequestId = requestId;
      g_aiPendingOrderKey  = orderKey;
      g_aiPendingTicket    = ticket;
      g_aiPendingSide      = side;
      g_aiPendingScore     = scoreAtEntry;
      g_aiPendingSentAt    = TimeCurrent();
     }
  }

bool WriteAIRequestFile(const string json)
  {
   string tempName = AIAsyncRequestFileName + ".tmp";

   ResetLastError();
   int handle = FileOpen(tempName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      Print("ASTUR IA: no se pudo escribir ", tempName, ". Error=", GetLastError());
      return(false);
     }
   FileWriteString(handle, json);
   FileClose(handle);

   ResetLastError();
   if(!FileMove(tempName, 0, AIAsyncRequestFileName, FILE_REWRITE))
     {
      Print("ASTUR IA: no se pudo mover ", tempName, " a ", AIAsyncRequestFileName, ". Error=", GetLastError());
      FileDelete(tempName);
      return(false);
     }

   return(true);
  }

void AIManageCheckPollResponse(const int type)
  {
   if(TimeCurrent() - g_aiPendingSentAt > AIAsyncTimeoutSec)
     {
      LogAIDecision("MANAGE", g_aiPendingTicket, g_aiPendingSide, g_aiPendingScore,
                    "SIN_RESPUESTA", 0.0, "timeout esperando al puente (async)");
      g_aiPendingRequestId = "";
      g_aiPendingOrderKey  = "";
      return;
     }

   if(!FileIsExist(AIAsyncResponseFileName))
      return; // todavia no ha respondido; se revisa de nuevo en el proximo tick

   int handle = FileOpen(AIAsyncResponseFileName, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle);
   FileClose(handle);

   ResetLastError();
   FileDelete(AIAsyncResponseFileName);

   string parts[];
   int n = StringSplit(content, '|', parts);
   if(n < 4 || parts[0] != g_aiPendingRequestId)
      return; // respuesta ajena, corrupta o de un ciclo anterior: se ignora sin actuar

   string action     = parts[1];
   double confidence  = StringToDouble(parts[2]);
   string reason      = parts[3];
   for(int i = 4; i < n; i++)
      reason += "|" + parts[i];

   int    ticket = g_aiPendingTicket;
   string side   = g_aiPendingSide;
   int    score  = g_aiPendingScore;

   g_aiPendingRequestId = "";
   g_aiPendingOrderKey  = "";

   LogAIDecision("MANAGE", ticket, side, score, action, confidence, reason);

   if(AIShadowMode)
      return; // solo registra, nunca actua

   if(confidence < AIMinConfidence)
      return;

   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return; // la operacion ya no existe con ese ticket; no se actua sobre nada

   if(action == "PROTECT" && AIAllowProtectiveStop)
      ApplyAIProtect(ticket, type);
   else if(action == "CLOSE" && AIAllowEarlyClose)
      CloseTicketImmediately(ticket);
  }

void ReportTradeOutcome(const string orderKey)
  {
   if(!UseLocalAI)
     {
      CleanupOrderState(orderKey);
      return;
     }

   datetime targetOpenTime = (datetime)StringToInteger(orderKey);
   double   totalProfit    = 0.0;
   int      rootTicket     = 0;
   string   side           = "";
   bool     found          = false;

   for(int i = OrdersHistoryTotal() - 1; i >= 0; i--)
     {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
         continue;
      if(OrderOpenTime() != targetOpenTime)
         continue;

      int type = OrderType();
      if(type != OP_BUY && type != OP_SELL)
         continue;

      totalProfit += OrderProfit() + OrderSwap() + OrderCommission();
      if(!found)
        {
         rootTicket = OrderTicket();
         side       = (type == OP_BUY ? "BUY" : "SELL");
         found      = true;
        }
     }

   if(found)
     {
      int    score  = GlobalVariableCheck(g_statePrefix + "SCORE_" + orderKey) ?
                       (int)GlobalVariableGet(g_statePrefix + "SCORE_" + orderKey) : -1;
      string result = (totalProfit >= 0.0 ? "WIN" : "LOSS");

      string json = "{" +
                    "\"root_ticket\":" + IntegerToString(rootTicket) + "," +
                    "\"side\":\"" + side + "\"," +
                    "\"score\":" + IntegerToString(score) + "," +
                    "\"profit\":" + DoubleToString(totalProfit, 2) + "," +
                    "\"result\":\"" + result + "\"" +
                    "}";

      string response;
      CallAIBridge("/outcome", json, response);

      AppendToCsv(AIOutcomesFileName,
         "Timestamp,RootTicket,Side,Score,Profit,Resultado",
         TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "," +
         IntegerToString(rootTicket) + "," + side + "," + IntegerToString(score) + "," +
         DoubleToString(totalProfit, 2) + "," + result);
     }

   CleanupOrderState(orderKey);
  }

//+------------------------------------------------------------------+
//| Diagnostico: log CSV de cada senal evaluada (tomada o no)         |
//+------------------------------------------------------------------+
string CsvSafe(string text)
  {
   StringReplace(text, ",", ";");
   StringReplace(text, "\n", " ");
   StringReplace(text, "\r", " ");
   return(text);
  }

void AppendToCsv(const string fileName, const string header, const string line)
  {
   bool needsHeader = !FileIsExist(fileName);
   int handle = FileOpen(fileName, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      Print("ASTUR Safe EA: no se pudo abrir ", fileName, " para diagnostico. Error=", GetLastError());
      return;
     }

   FileSeek(handle, 0, SEEK_END);
   if(needsHeader)
      FileWriteString(handle, header + "\r\n");
   FileWriteString(handle, line + "\r\n");
   FileClose(handle);
  }

void LogSignalDiagnostic(const AsturSignalContext &ctx, const string blockReason, const string tradeResult,
                          const int ticket, const double lots, const double sl, const double tp)
  {
   if(!UseDiagnosticsLog)
      return;

   RefreshRates();
   double spreadPips = SpreadPointsToPips(CurrentSpreadPoints());

   string cruceStr = (ctx.crossDirection > 0 ? "ALCISTA" : (ctx.crossDirection < 0 ? "BAJISTA" : "NINGUNO"));
   string senalStr  = (ctx.finalSignal > 0 ? "BUY" : (ctx.finalSignal < 0 ? "SELL" : "NONE"));

   string line = TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "," +
                 Symbol() + "," +
                 DoubleToString(ctx.close1, Digits) + "," +
                 DoubleToString(ctx.fast1, Digits) + "," +
                 DoubleToString(ctx.slow1, Digits) + "," +
                 DoubleToString(ctx.trend1, Digits) + "," +
                 DoubleToString(ctx.adx1, 2) + "," +
                 DoubleToString(ctx.plus1, 2) + "," +
                 DoubleToString(ctx.minus1, 2) + "," +
                 DoubleToString(ctx.atrPips, 2) + "," +
                 DoubleToString(ctx.candleRatio, 2) + "," +
                 cruceStr + "," +
                 IntegerToString(ctx.confluenceScore) + "," +
                 IntegerToString(ctx.confluenceMax) + "," +
                 (ctx.htfOk ? "SI" : "NO") + "," +
                 (ctx.trendSlopeOk ? "SI" : "NO") + "," +
                 (ctx.adxSlopeOk ? "SI" : "NO") + "," +
                 senalStr + "," +
                 CsvSafe(blockReason) + "," +
                 tradeResult + "," +
                 IntegerToString(ticket) + "," +
                 DoubleToString(lots, LotDigits()) + "," +
                 DoubleToString(sl, Digits) + "," +
                 DoubleToString(tp, Digits) + "," +
                 DoubleToString(spreadPips, 2);

   AppendToCsv(DiagnosticsFileName,
      "Timestamp,Simbolo,Cierre,EMA_Fast,EMA_Slow,EMA_Trend,ADX,DIplus,DIminus,ATR_pips,CandleATRratio,Cruce,ConfluenceScore,ConfluenceMax,HTF_OK,TrendSlopeOK,ADXSlopeOK,Senal,Bloqueo,Resultado,Ticket,Lotes,SL,TP,SpreadPips",
      line);
  }

//+------------------------------------------------------------------+
//| Utilidades                                                        |
//+------------------------------------------------------------------+
bool IsNewBar()
  {
   datetime currentBar = iTime(NULL, PERIOD_M15, 0);
   if(currentBar <= 0 || currentBar == g_lastBarTime)
      return(false);

   g_lastBarTime = currentBar;
   return(true);
  }

int CountEAOrders()
  {
   int count = 0;
   for(int pos = OrdersTotal() - 1; pos >= 0; pos--)
     {
      if(!OrderSelect(pos, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() == MagicNumber && OrderSymbol() == Symbol())
         count++;
     }
   return(count);
  }

double PipSize()
  {
   if(Digits == 3 || Digits == 5)
      return(Point * 10.0);
   return(Point);
  }

int PipsToPoints(const double pips)
  {
   double factor = (Digits == 3 || Digits == 5) ? 10.0 : 1.0;
   return((int)MathRound(pips * factor));
  }

int CurrentSpreadPoints()
  {
   // MODE_SPREAD devuelve el spread actual en puntos del simbolo.
   return((int)MathMax(0.0, MathRound(MarketInfo(Symbol(), MODE_SPREAD))));
  }

double SpreadPointsToPips(const int spreadPoints)
  {
   double factor = (Digits == 3 || Digits == 5) ? 10.0 : 1.0;
   return(spreadPoints / factor);
  }

int LotDigits()
  {
   double step = MarketInfo(Symbol(), MODE_LOTSTEP);
   if(step >= 1.0)
      return(0);
   if(step >= 0.1)
      return(1);
   if(step >= 0.01)
      return(2);
   return(3);
  }

double CurrentDrawdownPct()
  {
   double peak = GlobalVariableGet(g_statePrefix + "PEAK_EQ");
   if(peak <= 0.0)
      return(0.0);
   return(MathMax(0.0, (peak - AccountEquity()) / peak * 100.0));
  }

void UpdateDashboard()
  {
   RefreshRates();
   double spreadPips = SpreadPointsToPips(CurrentSpreadPoints());

   string newsLine = "Noticias: inactivo";
   if(UseNewsFilter)
      newsLine = g_newsFileMissing ?
                 "Noticias: ACTIVO, archivo no encontrado (bloqueando entradas)" :
                 "Noticias: activo, " + IntegerToString(g_newsCount) + " eventos";

   string diagLine = UseDiagnosticsLog ? "Diagnostico: activo (" + DiagnosticsFileName + ")" : "Diagnostico: inactivo";

   string aiLine = "IA: desactivada";
   if(UseLocalAI)
      aiLine = AIShadowMode ?
               "IA: activa en modo SOMBRA (solo observa)" :
               "IA: ACTIVA (puede vetar/proteger/cerrar segun permisos)";

   Comment("ASTUR Safe EA v0.42\n",
           "Modo: ", (IsDemo() ? "DEMO" : "REAL"),
           " | Real permitido: ", (AllowRealAccount ? "SI" : "NO"), "\n",
           "Cuenta: ", AccountNumber(), " | ", Symbol(), " M15\n",
           "Equity: ", DoubleToString(AccountEquity(), 2),
           " | DD: ", DoubleToString(CurrentDrawdownPct(), 2), "%\n",
           "Riesgo/operacion: ", DoubleToString(RiskPerTradePct, 2),
           "% | Spread: ", DoubleToString(spreadPips, 2), " pips\n",
           newsLine, "\n",
           diagLine, "\n",
           aiLine, "\n",
           "Operaciones EA: ", CountEAOrders(), "\n",
           "Estado: ", g_status);
  }
