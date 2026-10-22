//+------------------------------------------------------------------+
//| GoldAIBridge.mq5                                                  |
//| READ-ONLY market-data bridge for GOLD AI ADAPTIVE AGENTIC SCALPER |
//|                                                                   |
//| - Streams every Bid/Ask tick of the chart symbol to a CSV file in |
//|   the terminal's Common\Files folder (one file per broker/symbol/  |
//|   day) for the Python collector to ingest.                        |
//| - Writes a symbol-specification snapshot (JSON) on start.         |
//| - Displays the latest AI signal written by the Python backend.    |
//|                                                                   |
//| This EA contains NO trading functions (no OrderSend / CTrade).    |
//| Execution is handled by the authorization-gated Python adapter.   |
//|                                                                   |
//| STATUS: not yet compiled in MetaEditor — verify on the VPS.       |
//+------------------------------------------------------------------+
#property copyright "GOLD AI ADAPTIVE AGENTIC SCALPER"
#property version   "0.10"
#property strict

input string InpFilePrefix   = "goldai";   // file name prefix in Common\Files
input int    InpFlushEvery   = 50;         // flush to disk every N ticks
input string InpSignalFile   = "goldai_signal.txt";

int    g_handle = INVALID_HANDLE;
string g_day    = "";
int    g_count  = 0;

string BrokerTag()
  {
   string s = AccountInfoString(ACCOUNT_SERVER);
   StringReplace(s, " ", "_");
   return s;
  }

bool OpenDayFile()
  {
   string day = TimeToString(TimeGMT(), TIME_DATE);
   StringReplace(day, ".", "");
   if(day == g_day && g_handle != INVALID_HANDLE)
      return true;
   if(g_handle != INVALID_HANDLE)
      FileClose(g_handle);
   g_day = day;
   string name = StringFormat("%s_%s_%s_%s.csv", InpFilePrefix, BrokerTag(), _Symbol, day);
   bool exists = FileIsExist(name, FILE_COMMON);
   g_handle = FileOpen(name, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ, ',');
   if(g_handle == INVALID_HANDLE)
     {
      PrintFormat("GoldAIBridge: cannot open %s (error %d)", name, GetLastError());
      return false;
     }
   FileSeek(g_handle, 0, SEEK_END);
   if(!exists)
      FileWrite(g_handle, "time", "bid", "ask", "volume");
   return true;
  }

void WriteSpec()
  {
   string name = StringFormat("%s_%s_%s_spec.json", InpFilePrefix, BrokerTag(), _Symbol);
   int h = FileOpen(name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;
   string json = StringFormat(
      "{\"server\":\"%s\",\"login\":%I64d,\"currency\":\"%s\",\"trade_mode\":%d,"
      "\"symbol\":\"%s\",\"digits\":%d,\"point\":%.10f,\"tick_size\":%.10f,\"tick_value\":%.10f,"
      "\"contract_size\":%.4f,\"volume_min\":%.4f,\"volume_max\":%.4f,\"volume_step\":%.4f,"
      "\"stops_level\":%d,\"freeze_level\":%d,\"swap_long\":%.6f,\"swap_short\":%.6f,\"swap_mode\":%d,"
      "\"currency_base\":\"%s\",\"currency_profit\":\"%s\",\"filling_mode\":%d,\"exec_mode\":%d}",
      AccountInfoString(ACCOUNT_SERVER), AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_CURRENCY),
      (int)AccountInfoInteger(ACCOUNT_TRADE_MODE), _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
      SymbolInfoDouble(_Symbol, SYMBOL_POINT), SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL), SymbolInfoDouble(_Symbol, SYMBOL_SWAP_LONG),
      SymbolInfoDouble(_Symbol, SYMBOL_SWAP_SHORT), (int)SymbolInfoInteger(_Symbol, SYMBOL_SWAP_MODE),
      SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE), SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE), (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_EXEMODE));
   FileWriteString(h, json);
   FileClose(h);
  }

void ShowSignal()
  {
   if(!FileIsExist(InpSignalFile, FILE_COMMON))
      return;
   int h = FileOpen(InpSignalFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return;
   string text = "";
   while(!FileIsEnding(h))
      text += FileReadString(h) + "\n";
   FileClose(h);
   Comment("GOLD AI (signal only, no orders from this EA)\n", text);
  }

int OnInit()
  {
   WriteSpec();
   if(!OpenDayFile())
      return INIT_FAILED;
   EventSetTimer(2);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_handle != INVALID_HANDLE)
      FileClose(g_handle);
   Comment("");
  }

void OnTick()
  {
   MqlTick t;
   if(!SymbolInfoTick(_Symbol, t))
      return;
   if(!OpenDayFile())
      return;
   // time_msc is trade-server time; the Python side converts using the configured offset.
   FileWrite(g_handle, (string)t.time_msc, DoubleToString(t.bid, _Digits), DoubleToString(t.ask, _Digits),
             DoubleToString(t.volume_real, 2));
   if(++g_count % InpFlushEvery == 0)
      FileFlush(g_handle);
  }

void OnTimer()
  {
   if(g_handle != INVALID_HANDLE)
      FileFlush(g_handle);
   ShowSignal();
  }
//+------------------------------------------------------------------+
