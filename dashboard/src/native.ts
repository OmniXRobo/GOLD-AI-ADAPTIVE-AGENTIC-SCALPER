/**
 * Bridge to the Android app (android/ in the repo). The app's WebView exposes
 * `window.GoldAIApp`; in a normal browser it is absent and every call is a no-op.
 */
interface GoldAIAppBridge {
  onSession(token: string): void;
  openSettings(): void;
  appVersion(): string;
  alertsEnabled(): boolean;
}

function bridge(): GoldAIAppBridge | null {
  const b = (window as unknown as { GoldAIApp?: GoldAIAppBridge }).GoldAIApp;
  return b && typeof b.onSession === "function" ? b : null;
}

export const nativeApp = {
  available: () => bridge() !== null,
  /** Lets the app request its own read-only device token for background signal alerts. */
  onSession: (token: string) => {
    try {
      bridge()?.onSession(token);
    } catch {
      /* the app is optional */
    }
  },
  openSettings: () => bridge()?.openSettings(),
  version: () => {
    try {
      return bridge()?.appVersion() ?? null;
    } catch {
      return null;
    }
  },
  alertsEnabled: () => {
    try {
      return bridge()?.alertsEnabled() ?? false;
    } catch {
      return false;
    }
  },
};
