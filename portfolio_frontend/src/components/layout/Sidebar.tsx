import { NavLink } from 'react-router-dom';

export default function Sidebar() {
  return (
    <nav className="sidebar" aria-label="Main navigation">
      <div className="sidebar-brand">
        <span className="brand-icon">&#9670;</span>
        <span className="brand-text">Portfolio Lab</span>
      </div>
      <div className="sidebar-links">
        <NavLink to="/" aria-label="New Analysis" title="New Analysis" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <span className="nav-icon" aria-hidden="true">+</span><span>New Analysis</span>
        </NavLink>
        <NavLink to="/history" aria-label="History" title="History" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <span className="nav-icon" aria-hidden="true">&#9776;</span><span>History</span>
        </NavLink>
      </div>
      <div className="sidebar-footer"><span className="terminal-eyebrow">Research workspace</span><p>Construct. Test. Inspect.</p><small>Historical analysis, not investment advice.</small></div>
    </nav>
  );
}
