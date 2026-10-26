"""Read-only audit of persisted trades: where did the results come from, and do the numbers add up?

Reads one memory domain's closed trades and reports, without changing anything:
- the headline figures computed exactly as the dashboard Results page does (a win is net P/L > 0; pips are
  the price move from fill to exit in the instrument's own pips), so a screenshot can be reconciled;
- breakdowns by symbol, style, exploration flag, entry rule, side, exit reason, regime, Dubai hour and
  strategy/model version;
- outcomes in R (net P/L / money at risk) with a bootstrap interval, the break-even win rate implied by the
  realized payoff, and a binomial test of the observed win rate against it;
- exit analysis (stop slippage, trailing give-back, MFE/MAE where recorded) and the cost breakdown;
- integrity checks: duplicates, overlapping positions, inconsistent money/price arithmetic, stops on the
  wrong side, exits before entries.
Figures are computed from the stored rows only; nothing is estimated or filled in.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import timedelta

from ..domain import ExitReason, Side, SimTrade
from ..instruments import instrument_for
from ..timeutil import get_tz
from .stats import bootstrap_ci, mean

_RULE_PATTERNS = (("momentum continuation", "momentum_continuation"), ("rejection near support", "rejection_support"),
                  ("rejection near resistance", "rejection_resistance"))


def pip_of(symbol: str) -> float:
    inst = instrument_for(symbol)
    return inst.pip_size if inst else 0.1


def trade_pips(t: SimTrade) -> float | None:
    """Same arithmetic as dashboard/src/results.ts `tradePips`."""
    if t.exit_price is None:
        return None
    move = t.exit_price - t.entry_price if t.side == Side.BUY else t.entry_price - t.exit_price
    return move / pip_of(t.symbol)


def entry_rule(t: SimTrade) -> str:
    setup = (t.context or {}).get("setup")
    if setup:
        return f"rule:{setup}"
    text = t.explanation or ""
    for needle, name in _RULE_PATTERNS:
        if needle in text:
            return name
    return "unknown"


def _is_exploration(t: SimTrade) -> bool:
    c = t.context or {}
    return bool(c.get("exploration")) or "[EXPLORATION]" in (t.explanation or "")


def _group(ts: list[SimTrade]) -> dict:
    n = len(ts)
    pips = [trade_pips(t) or 0.0 for t in ts]
    money = [t.net_pnl for t in ts]
    wins = sum(m > 0 for m in money)
    gp, gl = sum(m for m in money if m > 0), -sum(m for m in money if m <= 0)
    rs = [t.r_multiple for t in ts if t.initial_risk_money > 0]
    return {"trades": n, "wins": wins, "losses": n - wins, "win_rate": wins / n if n else None,
            "net_pips": sum(pips), "net_money": sum(money), "avg_r": mean(rs) if rs else None,
            "profit_factor": (gp / gl) if gl > 0 else None}


def _by(ts: list[SimTrade], key) -> dict[str, dict]:
    groups: dict[str, list[SimTrade]] = defaultdict(list)
    for t in ts:
        groups[str(key(t))].append(t)
    return {k: _group(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}


def _binom_sf_le(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def headline(ts: list[SimTrade]) -> dict:
    pips = [trade_pips(t) or 0.0 for t in ts]
    won = [p for p in pips if p > 0]
    lost = [-p for p in pips if p <= 0]
    money = [t.net_pnl for t in ts]
    wins = [t for t in ts if t.net_pnl > 0]
    losses = [t for t in ts if t.net_pnl <= 0]
    gpm, glm = sum(m for m in money if m > 0), -sum(m for m in money if m <= 0)
    win_pips = [trade_pips(t) or 0.0 for t in wins]
    loss_pips = [trade_pips(t) or 0.0 for t in losses]
    return {
        "trades": len(ts), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(ts) if ts else None,
        "pips_won": sum(won), "pips_lost": sum(lost), "net_pips": sum(won) - sum(lost),
        "profit_factor_pips": (sum(won) / sum(lost)) if sum(lost) > 0 else None,
        "avg_win_pips": mean(win_pips) if wins else None,
        "avg_loss_pips": -mean(loss_pips) if losses else None,
        "net_money": sum(money), "gross_profit_money": gpm, "gross_loss_money": glm,
        "profit_factor_money": (gpm / glm) if glm > 0 else None,
        # A trade can have positive pips but negative money (swap) or the reverse; the dashboard counts wins
        # by money and pips by price, so these are listed rather than hidden.
        "pip_money_sign_mismatches": sum((p > 0) != (t.net_pnl > 0) for p, t in zip(pips, ts)),
    }


def r_analysis(ts: list[SimTrade]) -> dict:
    rs = [t.r_multiple for t in ts if t.initial_risk_money > 0]
    if not rs:
        return {"trades_with_risk": 0}
    wr = [r for r in rs if r > 0]
    lr = [r for r in rs if r <= 0]
    out = {"trades_with_risk": len(rs), "expectancy_r": mean(rs), "ci90": bootstrap_ci(rs),
           "avg_win_r": mean(wr) if wr else None, "avg_loss_r": mean(lr) if lr else None}
    if wr and lr:
        w, l_ = mean(wr), -mean(lr)
        be = l_ / (w + l_)
        k, n = len(wr), len(rs)
        out.update(breakeven_win_rate=be, observed_win_rate=k / n,
                   p_value_win_rate_at_or_below=_binom_sf_le(k, n, be))
    return out


def exit_analysis(ts: list[SimTrade]) -> dict:
    out: dict = {}
    for reason in ExitReason:
        sub = [t for t in ts if t.exit_reason == reason]
        if not sub:
            continue
        rs = [t.r_multiple for t in sub if t.initial_risk_money > 0]
        holds = sorted((t.exit_time - t.entry_time).total_seconds() for t in sub if t.exit_time)
        out[reason.value] = {"trades": len(sub), "avg_r": mean(rs) if rs else None,
                             "median_hold_seconds": holds[len(holds) // 2] if holds else None,
                             "net_pips": sum(trade_pips(t) or 0.0 for t in sub)}
    stops = [t for t in ts if t.exit_reason == ExitReason.STOP_LOSS and t.initial_risk_money > 0]
    if stops:
        out["stop_loss_realized_vs_planned"] = mean([-t.r_multiple for t in stops])
    # MFE/MAE are recorded for trades closed after the audit change only.
    rec = [t for t in ts if "max_favorable_price" in (t.context or {}) and "initial_stop_loss" in t.context]
    if rec:
        def r_of(t, x):
            d = abs(t.entry_price - t.context["initial_stop_loss"])
            return x / d if d > 0 else 0.0
        losers = [t for t in rec if t.net_pnl <= 0]
        winners = [t for t in rec if t.net_pnl > 0]
        out["mfe_mae"] = {
            "recorded_trades": len(rec),
            "losers_that_reached_+0.5R": sum(r_of(t, t.context["max_favorable_price"]) >= 0.5 for t in losers),
            "losers_that_reached_+1R": sum(r_of(t, t.context["max_favorable_price"]) >= 1.0 for t in losers),
            "avg_winner_mfe_r": mean([r_of(t, t.context["max_favorable_price"]) for t in winners]) if winners else None,
            "avg_winner_realized_r": mean([t.r_multiple for t in winners]) if winners else None,
            "avg_mae_r": mean([r_of(t, t.context["max_adverse_price"]) for t in rec]),
        }
    else:
        out["mfe_mae"] = {"recorded_trades": 0,
                          "note": "MFE/MAE and the initial stop were not stored for these trades"}
    return out


def cost_analysis(ts: list[SimTrade]) -> dict:
    risk = [t.initial_risk_money for t in ts if t.initial_risk_money > 0]
    tot = {k: sum(getattr(t, k) for t in ts) for k in ("spread_cost", "slippage_cost", "commission", "swap")}
    per_r = [(t.spread_cost + t.slippage_cost + t.commission - t.swap) / t.initial_risk_money
             for t in ts if t.initial_risk_money > 0]
    stop_d = [abs(t.entry_price - (t.context or {}).get("initial_stop_loss", t.stop_loss)) / pip_of(t.symbol)
              for t in ts]
    return {**tot, "avg_cost_r": mean(per_r) if per_r else None, "avg_risk_money": mean(risk) if risk else None,
            "median_stop_distance_pips": sorted(stop_d)[len(stop_d) // 2] if stop_d else None,
            "stop_distance_note": ("initial stop from context" if all("initial_stop_loss" in (t.context or {})
                                                                      for t in ts)
                                   else "some stops are the final (trailed) stop; the initial stop was not stored")}


def integrity(ts: list[SimTrade]) -> dict:
    issues: dict[str, list] = defaultdict(list)
    seen: dict[tuple, str] = {}
    for t in ts:
        k = (t.broker, t.symbol, t.side.value, t.entry_time.isoformat(), round(t.entry_price, 6))
        if k in seen:
            issues["duplicate_entries"].append([seen[k], t.trade_id])
        seen[k] = t.trade_id
        if t.exit_time is not None and t.exit_time < t.entry_time:
            issues["exit_before_entry"].append(t.trade_id)
        if abs(t.net_pnl - (t.gross_pnl - t.commission + t.swap)) > 1e-6:
            issues["net_not_gross_minus_costs"].append(t.trade_id)
        sl0 = (t.context or {}).get("initial_stop_loss")
        if sl0 is not None and ((t.side == Side.BUY and sl0 >= t.entry_price) or
                                (t.side == Side.SELL and sl0 <= t.entry_price)):
            issues["initial_stop_wrong_side"].append(t.trade_id)
    # Money per (price unit x lot) must be constant per symbol (= contract size for USD-quoted symbols).
    implied: dict[str, list[float]] = defaultdict(list)
    for t in ts:
        mv = (t.exit_price - t.entry_price) if t.exit_price is not None else 0.0
        if abs(mv) > 0 and t.lots > 0:
            implied[t.symbol].append(abs(t.gross_pnl) / (abs(mv) * t.lots))
    contract = {s: {"min": min(v), "max": max(v)} for s, v in implied.items()}
    for s, v in contract.items():
        if v["max"] > v["min"] * 1.01:
            issues["inconsistent_money_per_price"].append(s)
    # One position at a time per engine (broker, symbol, account, style).
    lanes: dict[tuple, list[SimTrade]] = defaultdict(list)
    for t in ts:
        lanes[(t.broker, t.symbol, t.account, (t.context or {}).get("style", "scalp"))].append(t)
    for lane, xs in lanes.items():
        xs = sorted(xs, key=lambda t: t.entry_time)
        for a, b in zip(xs, xs[1:]):
            if a.exit_time is not None and b.entry_time < a.exit_time:
                issues["overlapping_positions"].append([a.trade_id, b.trade_id])
    return {"issues": {k: v for k, v in issues.items()}, "implied_money_per_price_lot": contract,
            "clean": not issues}


def spacing(ts: list[SimTrade]) -> dict:
    """How soon a new trade followed the previous exit in the same engine (re-entry / overtrading)."""
    lanes: dict[tuple, list[SimTrade]] = defaultdict(list)
    for t in ts:
        lanes[(t.broker, t.symbol, (t.context or {}).get("style", "scalp"))].append(t)
    gaps = []
    for xs in lanes.values():
        xs = sorted(xs, key=lambda t: t.entry_time)
        gaps += [(b.entry_time - a.exit_time).total_seconds() for a, b in zip(xs, xs[1:]) if a.exit_time]
    gaps.sort()
    return {"median_gap_seconds": gaps[len(gaps) // 2] if gaps else None,
            "reentries_within_60s": sum(g < 60 for g in gaps),
            "reentries_after_loss_within_300s": None if not gaps else _after_loss(lanes, 300)}


def _after_loss(lanes, secs: float) -> int:
    n = 0
    for xs in lanes.values():
        xs = sorted(xs, key=lambda t: t.entry_time)
        n += sum(1 for a, b in zip(xs, xs[1:]) if a.exit_time and a.net_pnl <= 0
                 and (b.entry_time - a.exit_time) <= timedelta(seconds=secs))
    return n


def audit_trades(ts: list[SimTrade], *, domain: str, filters: dict | None = None,
                 local_timezone: str = "Asia/Dubai") -> dict:
    ts = sorted((t for t in ts if t.exit_time is not None), key=lambda t: t.entry_time)
    tz = get_tz(local_timezone)
    out = {"domain": domain, "filters": filters or {}, "closed_trades": len(ts)}
    if not ts:
        return {**out, "note": "no closed trades match"}
    out.update(
        period={"first_entry": ts[0].entry_time.isoformat(), "last_exit": max(t.exit_time for t in ts).isoformat()},
        headline=headline(ts),
        r=r_analysis(ts),
        by_symbol=_by(ts, lambda t: t.symbol),
        by_style=_by(ts, lambda t: (t.context or {}).get("style", "scalp")),
        by_exploration=_by(ts, lambda t: "exploration" if _is_exploration(t) else "model-approved"),
        by_entry_rule=_by(ts, entry_rule),
        by_side=_by(ts, lambda t: t.side.value),
        by_exit_reason=_by(ts, lambda t: t.exit_reason.value if t.exit_reason else "open"),
        by_regime=_by(ts, lambda t: (t.context or {}).get("regime", "unknown")),
        by_local_hour=_by(ts, lambda t: f"{t.entry_time.astimezone(tz).hour:02d}"),
        by_strategy_version=_by(ts, lambda t: t.strategy_version),
        by_model_version_count=len({t.model_version for t in ts}),
        exits=exit_analysis(ts),
        costs=cost_analysis(ts),
        spacing=spacing(ts),
        integrity=integrity(ts),
    )
    return out


def _f(x, d=2, pct=False) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return str(x)
    return f"{x * 100:.1f}%" if pct else (f"{x:,.{d}f}" if isinstance(x, (int, float)) else str(x))


def _table(title: str, groups: dict[str, dict]) -> list[str]:
    lines = [f"### {title}", "", "| Group | Trades | Win rate | Net pips | Net money | Avg R | PF |",
             "|---|---|---|---|---|---|---|"]
    for k, g in groups.items():
        lines.append(f"| {k} | {g['trades']} | {_f(g['win_rate'], pct=True)} | {_f(g['net_pips'], 0)} | "
                     f"{_f(g['net_money'])} | {_f(g['avg_r'])} | {_f(g['profit_factor'])} |")
    return lines + [""]


def audit_markdown(rep: dict) -> str:
    lines = [f"# Trade audit: {rep['domain']}", "", f"Filters: {rep['filters'] or 'none'}. "
             f"Closed trades: {rep['closed_trades']}.", ""]
    if not rep["closed_trades"]:
        return "\n".join(lines + [rep.get("note", "")]) + "\n"
    h, r = rep["headline"], rep["r"]
    lines += [f"Period: {rep['period']['first_entry']} to {rep['period']['last_exit']}", "",
              "## Headline (dashboard arithmetic)", "",
              f"- Trades {h['trades']}: {h['wins']} wins / {h['losses']} losses, win rate {_f(h['win_rate'], pct=True)}",
              f"- Pips: +{_f(h['pips_won'], 0)} / -{_f(h['pips_lost'], 0)}, net {_f(h['net_pips'], 0)}; "
              f"PF (pips) {_f(h['profit_factor_pips'])}",
              f"- Average win {_f(h['avg_win_pips'], 1)} pips, average loss {_f(h['avg_loss_pips'], 1)} pips",
              f"- Money: net {_f(h['net_money'])}, PF (money) {_f(h['profit_factor_money'])}",
              f"- Trades whose pip sign and money sign differ: {h['pip_money_sign_mismatches']}", "",
              "## Outcomes in R", ""]
    if r.get("trades_with_risk"):
        lines += [f"- Expectancy {_f(r['expectancy_r'])}R, 90% CI {r['ci90'] and tuple(round(x, 2) for x in r['ci90'])}",
                  f"- Average win {_f(r['avg_win_r'])}R, average loss {_f(r['avg_loss_r'])}R"]
        if "breakeven_win_rate" in r:
            lines += [f"- Break-even win rate at this payoff {_f(r['breakeven_win_rate'], pct=True)}; observed "
                      f"{_f(r['observed_win_rate'], pct=True)}; P(win rate this low | break-even) = "
                      f"{_f(r['p_value_win_rate_at_or_below'], 3)}"]
    lines.append("")
    for key, title in (("by_exploration", "Exploration vs model-approved"), ("by_entry_rule", "Entry rule"),
                       ("by_symbol", "Symbol"), ("by_style", "Style"), ("by_side", "Side"),
                       ("by_exit_reason", "Exit reason"), ("by_regime", "Regime at entry"),
                       ("by_local_hour", "Entry hour (Dubai)"), ("by_strategy_version", "Strategy version")):
        lines += _table(title, rep[key])
    e, c, sp, ig = rep["exits"], rep["costs"], rep["spacing"], rep["integrity"]
    lines += ["## Exits", ""]
    for k, v in e.items():
        if isinstance(v, dict) and "trades" in v:
            lines.append(f"- {k}: {v['trades']} trades, avg {_f(v['avg_r'])}R, median hold "
                         f"{_f(v['median_hold_seconds'], 0)} s, net {_f(v['net_pips'], 0)} pips")
    if "stop_loss_realized_vs_planned" in e:
        lines.append(f"- Stop-loss exits lost {_f(e['stop_loss_realized_vs_planned'])}x the planned risk on average")
    lines += [f"- MFE/MAE: {e['mfe_mae']}", "", "## Costs", "",
              f"- Spread {_f(c['spread_cost'])}, slippage {_f(c['slippage_cost'])}, commission {_f(c['commission'])}, "
              f"swap {_f(c['swap'])}; average cost {_f(c['avg_cost_r'], 3)}R per trade",
              f"- Median stop distance {_f(c['median_stop_distance_pips'], 1)} pips ({c['stop_distance_note']})", "",
              "## Spacing", "", f"- Median gap after an exit {_f(sp['median_gap_seconds'], 0)} s; re-entries within 60 s: "
              f"{sp['reentries_within_60s']}; within 5 min of a loss: {sp['reentries_after_loss_within_300s']}", "",
              "## Integrity", "", f"- Clean: {ig['clean']}; issues: {ig['issues'] or 'none'}",
              f"- Implied money per price unit per lot: {ig['implied_money_per_price_lot']}", ""]
    return "\n".join(lines) + "\n"


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(s: str) -> str:
    return _SAFE.sub("_", s)
