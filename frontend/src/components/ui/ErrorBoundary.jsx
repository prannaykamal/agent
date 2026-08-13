import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="glass-card">
        <h3>This panel failed</h3>
        <p className="lede" style={{ marginTop: 8 }}>{this.state.error.message || String(this.state.error)}</p>
        <button
          className="btn btn-primary"
          style={{ marginTop: 14 }}
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    );
  }
}
