"use client";

import { Component, type ReactNode } from "react";

/** A lost renderer must not take the operator's job navigation with it. */
export class StudioViewport extends Component<
  { children: ReactNode; fallback: ReactNode; onUnavailable: () => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onUnavailable();
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
