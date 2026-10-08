import { Component, type ReactNode } from "react";

export function PageLoading() {
  return <div className="app-boot" role="status" aria-live="polite">Loading your workspace…</div>;
}

export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <div className="app-boot" role="alert">
        <p>This page could not be loaded. Please refresh to try again.</p>
        <button className="button button-primary" onClick={() => window.location.reload()}>Refresh page</button>
      </div>;
    }
    return this.props.children;
  }
}
