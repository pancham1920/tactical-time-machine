// Browser entry point: mount React into index.html's #root element.
// AccessGate chooses the entry screen; App owns the chat once access is available.
import React from 'react';
import { createRoot } from 'react-dom/client';
import AccessGate from './AccessGate.jsx';
import './index.css';

// StrictMode adds development checks; it does not enforce authentication.
createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AccessGate />
  </React.StrictMode>,
);
