//+------------------------------------------------------------------+
//| GoldAICalendar.mq5                                                |
//| READ-ONLY economic-calendar exporter for GOLD AI.                 |
//|                                                                   |
//| Every InpEveryMinutes it writes the MetaTrader economic calendar  |
//| (yesterday .. +InpDaysAhead days, selected currencies) to         |
//| Common\Files\goldai_calendar.csv in the format read by            |
//| gold_ai.news.CalendarFileSource. Times are converted to UTC.      |
//|                                                                   |
//| This EA contains NO trading functions (no OrderSend / CTrade).    |
//| Attach it to any chart of any terminal; one instance is enough.   |
//+------------------------------------------------------------------+
#property copyright "GOLD AI ADAPTIVE AGENTIC SCALPER"
#property version   "1.00"
#property strict

input string InpCurrencies   = "USD,EUR,GBP,JPY,CNY,CHF"; // currencies to export
input int    InpDaysAhead    = 14;                        // days ahead to export
input int    InpEveryMinutes = 15;                        // refresh interval
input string InpFileName     = "goldai_calendar.csv";     // file in Common\Files

string Quote(string s)
  {
   StringReplace(s, "\"", "\"\"");
   return "\"" + s + "\"";
  }

string Num(const bool has, const double v)
  {
   return has ? DoubleToString(v, 4) : "";
  }

string Impact(const ENUM_CALENDAR_EVENT_IMPORTANCE imp)
  {
   switch(imp)
     {
      case CALENDAR_IMPORTANCE_HIGH:     return "high";
      case CALENDAR_IMPORTANCE_MODERATE: return "medium";
      case CALENDAR_IMPORTANCE_LOW:      return "low";
      default:                           return "";
     }
  }

// Server-time offset from UTC, rounded to 30 minutes (calendar times are in trade-server time).
long ServerOffsetSeconds()
  {
   long diff = (long)(TimeTradeServer() - TimeGMT());
   return (long)MathRound(diff / 1800.0) * 1800;
  }

string IsoUtc(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:00Z", d.year, d.mon, d.day, d.hour, d.min);
  }

bool ExportCalendar()
  {
   string currencies[];
   int nc = StringSplit(InpCurrencies, ',', currencies);
   datetime from = TimeTradeServer() - 86400;
   datetime to   = TimeTradeServer() + (datetime)InpDaysAhead * 86400;
   long off = ServerOffsetSeconds();
   string tmp = InpFileName + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("GoldAICalendar: cannot open %s (error %d)", tmp, GetLastError());
      return false;
     }
   FileWriteString(h, "time,title,currency,impact,forecast,previous,actual\r\n");
   int rows = 0;
   for(int c = 0; c < nc; c++)
     {
      string cur = currencies[c];
      StringTrimLeft(cur);
      StringTrimRight(cur);
      MqlCalendarValue values[];
      if(CalendarValueHistory(values, from, to, NULL, cur) <= 0)
         continue;
      for(int i = 0; i < ArraySize(values); i++)
        {
         MqlCalendarEvent ev;
         if(!CalendarEventById(values[i].event_id, ev))
            continue;
         if(ev.type == CALENDAR_TYPE_HOLIDAY)
            continue;
         string line = IsoUtc(values[i].time - (datetime)off) + "," + Quote(ev.name) + "," + cur + "," +
                       Impact(ev.importance) + "," +
                       Num(values[i].HasForecastValue(), values[i].GetForecastValue()) + "," +
                       Num(values[i].HasPreviousValue(), values[i].GetPreviousValue()) + "," +
                       Num(values[i].HasActualValue(), values[i].GetActualValue()) + "\r\n";
         FileWriteString(h, line);
         rows++;
        }
     }
   FileClose(h);
   if(!FileMove(tmp, FILE_COMMON, InpFileName, FILE_COMMON | FILE_REWRITE))
     {
      PrintFormat("GoldAICalendar: cannot replace %s (error %d)", InpFileName, GetLastError());
      return false;
     }
   PrintFormat("GoldAICalendar: exported %d events (server offset %d s)", rows, off);
   return true;
  }

int OnInit()
  {
   EventSetTimer(60);                    // checks every minute; exports when InpEveryMinutes are due
   ExportIfDue();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

datetime g_last_export = 0;

void ExportIfDue()
  {
   if(TimeLocal() - g_last_export < MathMax(1, InpEveryMinutes) * 60)
      return;
   if(ExportCalendar())
      g_last_export = TimeLocal();
  }

// The timer alone proved unreliable on the VPS (one export, then none), so ticks also trigger
// the refresh; either path exports at most once per InpEveryMinutes.
void OnTimer()
  {
   ExportIfDue();
  }

void OnTick()
  {
   ExportIfDue();
  }
//+------------------------------------------------------------------+
