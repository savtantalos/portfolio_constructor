import { NavLink } from 'react-router-dom';

export default function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-icon">&#9670;</span>
        <span className="brand-text">Portfolio Lab</span>
      </div>
      <div className="sidebar-links">
        <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <span className="nav-icon">+</span> New Analysis
        </NavLink>
        <NavLink to="/history" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <span className="nav-icon">&#9776;</span> History
        </NavLink>
      </div>
    </nav>
  );
}
