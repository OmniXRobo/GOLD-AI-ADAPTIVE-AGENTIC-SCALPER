import { Icon } from "../components/icons";
import { FAQ, HOW } from "../content";

const FEATURES: [string, string, string][] = [
  ["agent", "Self-learning AI", "Trades a virtual account on live XAUUSD ticks, learns from every closed trade and keeps its own version history."],
  ["signals", "Signals with levels", "Entry, stop loss and take profit with confidence and reward-to-risk, sent to the app, the dashboard and Telegram."],
  ["performance", "Live analysis", "Technical sentiment from live candles, US data surprises, Fed events and an economic calendar."],
  ["risk", "Risk first", "An independent risk engine vetoes trades: daily loss cap, spread and news filters, no martingale or grid."],
  ["practice", "Practice mode", "Paper trade gold on the live price with practice money before risking your own."],
  ["phone", "Android app", "The full dashboard on your phone, with signal alerts."],
];

export default function LandingPage({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="market" size={18} />
          </span>
          <span className="brand-name">
            Gold AI <small>Adaptive Agentic Scalper</small>
          </span>
        </div>
        <nav>
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#faq">FAQ</a>
          <button className="btn btn-primary btn-small" onClick={onSignIn}>
            Sign in
          </button>
        </nav>
      </header>

      <section className="landing-hero">
        <h1>Your AI assistant for trading gold</h1>
        <p>
          An adaptive, self-learning XAUUSD system for MetaTrader 5: live analysis, signals with clear levels and an AI that learns from every trade, under strict risk control.
        </p>
        <div className="landing-cta">
          <button className="btn btn-primary" onClick={onSignIn}>
            Sign in to the dashboard
          </button>
          <a className="btn" href="#how">
            How it works
          </a>
        </div>
        <p className="landing-note">Results are shown inside the dashboard only from trades that actually closed. No promises of returns.</p>
      </section>

      <section id="features" className="landing-section">
        <h2>Features</h2>
        <div className="landing-grid">
          {FEATURES.map(([icon, title, text]) => (
            <div className="landing-card" key={title}>
              <span className="quick-icon">
                <Icon name={icon} size={20} />
              </span>
              <b>{title}</b>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="landing-section">
        <h2>How it works</h2>
        <ol className="steps">
          {HOW.map(([t, d], i) => (
            <li key={t}>
              <span className="step-n">{i + 1}</span>
              <div>
                <b>{t}</b>
                <p className="muted small">{d}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section id="faq" className="landing-section">
        <h2>Questions</h2>
        <div className="faq">
          {FAQ.map(([q, a]) => (
            <details key={q}>
              <summary>{q}</summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="landing-foot">
        <p>
          Trading gold and other leveraged products carries a high risk of losing money. Past results, virtual or real, do not guarantee future results. This platform
          provides analysis and signals, not financial advice.
        </p>
      </footer>
    </div>
  );
}
