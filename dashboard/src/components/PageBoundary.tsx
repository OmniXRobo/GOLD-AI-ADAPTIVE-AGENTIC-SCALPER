import { Component, type ReactNode } from "react";

/** Catches a page that failed to load or crashed, and offers Retry instead of leaving a blank or stuck screen. */
export class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="state state-error">
        <b>This page could not be opened.</b>
        <p className="small">{error.message || "Unknown error"}</p>
        <p className="small muted">The server may be busy or the app may have been updated. Retry reloads the page.</p>
        <button className="btn btn-primary" onClick={() => window.location.reload()}>
          Retry
        </button>
      </div>
    );
  }
}
