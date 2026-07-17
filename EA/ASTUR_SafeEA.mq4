#property strict
#property version   "0.32"
#property description "ASTUR Safe EA: prototipo demo-first para EURUSD M15"
#property description "Sin martingala, grid ni promedios. SL obligatorio y riesgo limitado."
#property description "v0.2: gestion de posicion por tick (breakeven/trailing), filtros de senal reforzados y filtro de noticias opcional via CSV."
#property description "v0.3: cierre parcial por R, entrada por puntuacion de confluencia, filtro de coste spread/SL y log de diagnostico en CSV."
#property description "v0.31: comparacion robusta del spread en puntos y diagnostico de cancelaciones de ejecucion."
#property description "v0.32: cierre parcial ligado a la hora de apertura de la operacion (a prueba de cambio de ticket), NO integracion de IA todavia."

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
//   co-localizada ni acceso a microestructura del order book. La gestion de
//   posicion (breakeven/trailing/cierre parcial) reacciona a cada tick
//   recibido, que es lo mas "en vivo" que esta plataforma permite.
// - AllowRealAccount=false bloquea cuentas reales por defecto.
// - El filtro de noticias (UseNewsFilter) NO descarga nada de internet: lee
//   un CSV local (MQL4/Files/<NewsFileName>) que el usuario debe mantener
//   actualizado manualmente o mediante un proceso externo. Si se activa y
//   el archivo falta o no se puede leer, el EA bloquea nuevas entradas por
//   seguridad (fail-safe), nunca al reves. Ver EA/README.md para el formato.
// - El puente de IA (EA/astur_ai_bridge.py) es un servicio aparte: este
//   .mq4 TODAVIA no le hace ninguna llamada WebRequest. Los inputs
//   UseLocalAI/AIShadowMode/etc. descritos en EA/ASTUR_AI_SETUP.md no
//   existen en este archivo hasta que se implemente esa integracion.
// - Ninguna mejora de este archivo esta validada con backtesting real: hay
//   que probarla en Strategy Tester (idealmente walk-forward) y despues en
//   una cuenta DEMO separada antes de considerar una cuenta real.

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

datetime g_lastBarTime      = 0;
string   g_statePrefix      = "";
string   g_status           = "Inicializando";
bool     g_riskStopAnnounced = false;
string   g_lastKnownOrderKey = "";

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
   Print("ASTUR Safe EA v0.32 iniciado. Cuenta=", AccountNumber(),
         ", modo=", (IsDemo() ? "DEMO" : "REAL"),
         ", simbolo=", Symbol(), ", periodo=M15");
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
   // cierre parcial), no solo al cierre de vela: es la parte mas "en vivo"
   // que MT4 permite.
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
      ExecuteSignal(ctx.finalSignal, ticket, lots, sl, tp);
      tradeResult = (ticket > 0 ? "ABIERTO" : "FALLIDO");
      if(ticket <= 0)
         blockReason = g_status;
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
void ExecuteSignal(const int signal, int &outTicket, double &outLots, double &outSL, double &outTP)
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
                          stopLoss, takeProfit, "ASTUR_SAFE_V0.32",
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
//| cierre parcial por R, luego breakeven / trailing por ATR en vivo. |
//| El SL solo se mueve para reducir riesgo, nunca para aumentarlo.   |
//| El estado de "cierre parcial ya hecho" se indexa por la hora de   |
//| apertura de la operacion, no por el ticket (ver ExecuteSignal),   |
//| y tras un cierre parcial se relocaliza la orden por posicion en   |
//| vez de asumir que el ticket sigue siendo el mismo.                |
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
         CleanupOrderState(g_lastKnownOrderKey);
         g_lastKnownOrderKey = "";
        }
      return;
     }

   string orderKey = IntegerToString((int)openTimeFound);
   g_lastKnownOrderKey = orderKey;

   if(!UseBreakEven && !UseTrailingStop && !UsePartialClose)
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
         return; // el cierre parcial fue en realidad un cierre total
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

   if(openType == OP_BUY)
     {
      double profit = Bid - openPrice;

      if(UseBreakEven && profit >= BreakEvenTriggerATR * atr)
         candidateSL = MathMax(candidateSL, openPrice + BreakEvenLockPips * PipSize());

      if(UseTrailingStop && profit >= TrailingStartATR * atr)
         candidateSL = MathMax(candidateSL, Bid - TrailingStepATR * atr);

      candidateSL = MathMin(candidateSL, Bid - minLockDist);

      if(candidateSL - currentSL < minStepPrice)
         return;
     }
   else
     {
      double profit = openPrice - Ask;

      if(UseBreakEven && profit >= BreakEvenTriggerATR * atr)
         candidateSL = MathMin(candidateSL, openPrice - BreakEvenLockPips * PipSize());

      if(UseTrailingStop && profit >= TrailingStartATR * atr)
         candidateSL = MathMin(candidateSL, Ask + TrailingStepATR * atr);

      candidateSL = MathMax(candidateSL, Ask + minLockDist);

      if(currentSL - candidateSL < minStepPrice)
         return;
     }

   candidateSL = NormalizeDouble(candidateSL, Digits);

   ResetLastError();
   if(!OrderModify(openTicket, openPrice, candidateSL, takeProfit, 0, clrYellow))
      Print("ASTUR Safe EA: OrderModify (breakeven/trailing) fallo ticket=", openTicket,
            ". Error=", GetLastError());
   else
      Print("ASTUR Safe EA: SL protegido actualizado. ticket=", openTicket,
            ", nuevoSL=", DoubleToString(candidateSL, Digits));
  }

void CleanupOrderState(const string orderKey)
  {
   if(orderKey == "")
      return;
   GlobalVariableDel(g_statePrefix + "RISK_" + orderKey);
   GlobalVariableDel(g_statePrefix + "PARTIAL_" + orderKey);
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

   Comment("ASTUR Safe EA v0.32\n",
           "Modo: ", (IsDemo() ? "DEMO" : "REAL"),
           " | Real permitido: ", (AllowRealAccount ? "SI" : "NO"), "\n",
           "Cuenta: ", AccountNumber(), " | ", Symbol(), " M15\n",
           "Equity: ", DoubleToString(AccountEquity(), 2),
           " | DD: ", DoubleToString(CurrentDrawdownPct(), 2), "%\n",
           "Riesgo/operacion: ", DoubleToString(RiskPerTradePct, 2),
           "% | Spread: ", DoubleToString(spreadPips, 2), " pips\n",
           newsLine, "\n",
           diagLine, "\n",
           "Operaciones EA: ", CountEAOrders(), "\n",
           "Estado: ", g_status);
  }
