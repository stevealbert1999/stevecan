#property strict
#property version   "0.20"
#property description "ASTUR Safe EA: prototipo demo-first para EURUSD M15"
#property description "Sin martingala, grid ni promedios. SL obligatorio y riesgo limitado."
#property description "v0.2: gestion de posicion por tick (breakeven/trailing), filtros de senal reforzados y filtro de noticias opcional via CSV."

// IMPORTANTE (leer antes de usar):
// - Ningun EA, por bueno que sea, puede garantizar ganancias ni evitar todas
//   las perdidas. Cualquiera que ofrezca eso miente. Este EA busca operar
//   con una ventaja estadistica razonable y un riesgo controlado, nada mas.
// - MetaTrader 4 NO es una plataforma de alta frecuencia (HFT). OnTick() se
//   ejecuta con cada tick que el broker envia (tipicamente decenas a
//   cientos de milisegundos de latencia, a veces mas), sin ejecucion
//   co-localizada ni acceso a microestructura del order book. La gestion de
//   posicion (breakeven/trailing) reacciona a cada tick recibido, que es lo
//   mas "en vivo" que esta plataforma permite, no trading de alta frecuencia
//   institucional.
// - AllowRealAccount=false bloquea cuentas reales por defecto.
// - El filtro de noticias (UseNewsFilter) NO descarga nada de internet: lee
//   un CSV local (MQL4/Files/<NewsFileName>) que el usuario debe mantener
//   actualizado manualmente o mediante un proceso externo. Si se activa y
//   el archivo falta o no se puede leer, el EA bloquea nuevas entradas por
//   seguridad (fail-safe), nunca al reves. Ver EA/README.md para el formato.
// - Probar primero en Strategy Tester y despues en una cuenta DEMO separada
//   antes de considerar una cuenta real, incluso con AllowRealAccount=true.

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

// Filtros de senal reforzados (cada uno reduce falsas entradas a costa de
// operar con menos frecuencia; ninguno elimina el riesgo, solo lo reduce)
input bool             UseHigherTimeframeFilter = true;
input ENUM_TIMEFRAMES  HigherTimeframe          = PERIOD_H1;
input int              HigherTrendEMAPeriod     = 200;
input bool             UseTrendSlopeFilter      = true;
input bool             UseADXSlopeFilter        = true;

// Gestion de posicion abierta en cada tick (breakeven / trailing por ATR)
input bool   UseBreakEven           = true;
input double BreakEvenTriggerATR    = 1.00;
input double BreakEvenLockPips      = 1.00;
input bool   UseTrailingStop        = true;
input double TrailingStartATR       = 1.50;
input double TrailingStepATR        = 1.00;
input double MinTrailingStepPips    = 0.50;

// Filtro de noticias opcional, basado en un CSV local (ver README)
input bool   UseNewsFilter          = false;
input string NewsFileName           = "ASTUR_News.csv";
input int    NewsBufferMinutesBefore= 30;
input int    NewsBufferMinutesAfter = 15;
input string NewsImpactFilter       = "HIGH";
input int    NewsReloadMinutes      = 60;

datetime g_lastBarTime = 0;
string   g_statePrefix = "";
string   g_status      = "Inicializando";
bool     g_riskStopAnnounced = false;

struct AsturNewsEvent
  {
   datetime time;
   string   impact;
  };

AsturNewsEvent g_newsEvents[];
int            g_newsCount       = 0;
datetime       g_newsLastLoad    = 0;
bool           g_newsFileMissing = false;

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
   Print("ASTUR Safe EA v0.2 iniciado. Cuenta=", AccountNumber(),
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

   // Gestion de la posicion abierta en cada tick (breakeven / trailing), no
   // solo al cierre de vela: es la parte mas "en vivo" que MT4 permite.
   ManageOpenPosition();

   MaybeReloadNews();

   // Las entradas nuevas solo se evaluan al aparecer una vela M15 nueva,
   // usando exclusivamente velas cerradas.
   if(!IsNewBar())
     {
      UpdateDashboard();
      return;
     }

   string blockReason = "";
   if(!CanOpenNewTrade(blockReason))
     {
      g_status = "Sin entrada: " + blockReason;
      UpdateDashboard();
      return;
     }

   int signal = GetClosedBarSignal();
   if(signal == 0)
     {
      g_status = "Sin senal valida en la ultima vela";
      UpdateDashboard();
      return;
     }

   ExecuteSignal(signal);
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

   if(UseNewsFilter && (NewsBufferMinutesBefore < 0 || NewsBufferMinutesAfter < 0 ||
      NewsReloadMinutes <= 0 || StringLen(NewsFileName) == 0))
     {
      Print("Parametros del filtro de noticias invalidos.");
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
   double spreadPips = (Ask - Bid) / PipSize();
   if(spreadPips > MaxSpreadPips)
     {
      reason = "spread alto: " + DoubleToString(spreadPips, 2) + " pips";
      return(false);
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Senal sobre velas cerradas                                        |
//+------------------------------------------------------------------+
int GetClosedBarSignal()
  {
   double fast1  = iMA(NULL, PERIOD_M15, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double fast2  = iMA(NULL, PERIOD_M15, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   double slow1  = iMA(NULL, PERIOD_M15, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double slow2  = iMA(NULL, PERIOD_M15, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   double trend1 = iMA(NULL, PERIOD_M15, TrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 1);
   double trend2 = iMA(NULL, PERIOD_M15, TrendEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, 2);
   double adx1   = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 1);
   double adx2   = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MAIN, 2);
   double plus1  = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_PLUSDI, 1);
   double minus1 = iADX(NULL, PERIOD_M15, ADXPeriod, PRICE_CLOSE, MODE_MINUSDI, 1);
   double atr1   = iATR(NULL, PERIOD_M15, ATRPeriod, 1);
   double open1  = iOpen(NULL, PERIOD_M15, 1);
   double close1 = iClose(NULL, PERIOD_M15, 1);

   if(atr1 <= 0.0)
      return(0);

   double atrPips    = atr1 / PipSize();
   double candleSize = MathAbs(close1 - open1);

   if(atrPips < MinimumATRPips || atrPips > MaximumATRPips)
      return(0);

   // Evita perseguir una vela anormalmente grande; no sustituye el filtro
   // de noticias economicas dedicado (ver UseNewsFilter).
   if(candleSize > atr1 * MaxSignalCandleATR)
      return(0);

   bool buySignal = (fast2 <= slow2 && fast1 > slow1 &&
                     close1 > trend1 && adx1 >= MinimumADX && plus1 > minus1);

   bool sellSignal = (fast2 >= slow2 && fast1 < slow1 &&
                      close1 < trend1 && adx1 >= MinimumADX && minus1 > plus1);

   // Filtros adicionales, cada uno opcional: exigen mas calidad a la senal
   // a costa de operar con menos frecuencia. Ninguno elimina el riesgo.
   if(buySignal && UseTrendSlopeFilter && !(trend1 > trend2))
      buySignal = false;
   if(sellSignal && UseTrendSlopeFilter && !(trend1 < trend2))
      sellSignal = false;

   if(buySignal && UseADXSlopeFilter && !(adx1 > adx2))
      buySignal = false;
   if(sellSignal && UseADXSlopeFilter && !(adx1 > adx2))
      sellSignal = false;

   if(buySignal && !HigherTimeframeAligned(1))
      buySignal = false;
   if(sellSignal && !HigherTimeframeAligned(-1))
      sellSignal = false;

   if(buySignal)
      return(1);
   if(sellSignal)
      return(-1);
   return(0);
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
void ExecuteSignal(const int signal)
  {
   RefreshRates();

   double spreadPips = (Ask - Bid) / PipSize();
   if(spreadPips > MaxSpreadPips)
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
                          stopLoss, takeProfit, "ASTUR_SAFE_V0.2",
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
//| Gestion de posicion abierta en cada tick (breakeven / trailing)   |
//| El SL solo se mueve para reducir riesgo, nunca para aumentarlo.   |
//+------------------------------------------------------------------+
void ManageOpenPosition()
  {
   if(!UseBreakEven && !UseTrailingStop)
      return;

   for(int pos = OrdersTotal() - 1; pos >= 0; pos--)
     {
      if(!OrderSelect(pos, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol())
         continue;

      int type = OrderType();
      if(type != OP_BUY && type != OP_SELL)
         continue;

      double atr = iATR(NULL, PERIOD_M15, ATRPeriod, 0);
      if(atr <= 0.0)
         continue;

      RefreshRates();

      int    ticket       = OrderTicket();
      double openPrice    = OrderOpenPrice();
      double currentSL    = OrderStopLoss();
      double takeProfit   = OrderTakeProfit();
      double minLockDist  = (MarketInfo(Symbol(), MODE_STOPLEVEL) + 2.0) * Point;
      double minStepPrice = MathMax(MinTrailingStepPips * PipSize(), Point);
      double candidateSL  = currentSL;

      if(type == OP_BUY)
        {
         double profit = Bid - openPrice;

         if(UseBreakEven && profit >= BreakEvenTriggerATR * atr)
            candidateSL = MathMax(candidateSL, openPrice + BreakEvenLockPips * PipSize());

         if(UseTrailingStop && profit >= TrailingStartATR * atr)
            candidateSL = MathMax(candidateSL, Bid - TrailingStepATR * atr);

         candidateSL = MathMin(candidateSL, Bid - minLockDist);

         if(candidateSL - currentSL < minStepPrice)
            continue;
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
            continue;
        }

      candidateSL = NormalizeDouble(candidateSL, Digits);

      ResetLastError();
      if(!OrderModify(ticket, openPrice, candidateSL, takeProfit, 0, clrYellow))
         Print("ASTUR Safe EA: OrderModify (breakeven/trailing) fallo ticket=", ticket,
               ". Error=", GetLastError());
      else
         Print("ASTUR Safe EA: SL protegido actualizado. ticket=", ticket,
               ", nuevoSL=", DoubleToString(candidateSL, Digits));
     }
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
   double spreadPips = 0.0;
   if(PipSize() > 0.0)
      spreadPips = (Ask - Bid) / PipSize();

   string newsLine = "Noticias: inactivo";
   if(UseNewsFilter)
      newsLine = g_newsFileMissing ?
                 "Noticias: ACTIVO, archivo no encontrado (bloqueando entradas)" :
                 "Noticias: activo, " + IntegerToString(g_newsCount) + " eventos";

   Comment("ASTUR Safe EA v0.2\n",
           "Modo: ", (IsDemo() ? "DEMO" : "REAL"),
           " | Real permitido: ", (AllowRealAccount ? "SI" : "NO"), "\n",
           "Cuenta: ", AccountNumber(), " | ", Symbol(), " M15\n",
           "Equity: ", DoubleToString(AccountEquity(), 2),
           " | DD: ", DoubleToString(CurrentDrawdownPct(), 2), "%\n",
           "Riesgo/operacion: ", DoubleToString(RiskPerTradePct, 2),
           "% | Spread: ", DoubleToString(spreadPips, 2), " pips\n",
           newsLine, "\n",
           "Operaciones EA: ", CountEAOrders(), "\n",
           "Estado: ", g_status);
  }
