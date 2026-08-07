/*
  ================================================================
  UNLIMITED OCR - SPA Router & Global State Controller
  ================================================================
*/

const appState = {
  currentView: 'landing',
  authMode: 'login',
  user: null,
  activeDashMode: 'gundam',
  currentTab: 'rendered',
  currentFile: null,
  isProcessing: false,
  extractedText: '',
  tokens: 0,
  tps: 0,
  latency: 0,
  pdfDoc: null,
  currentPdfPage: 1,
  totalPages: 1,
  pageImages: [],
  pageBboxes: {},
  ocrAbortController: null,
  ocrStreamTimer: null,
  ocrSpeed: 'medium'
};

// API helpers — support same-origin and approved split deployments.
function apiUrl(path) {
  const base = (typeof window !== 'undefined' && window.API_BASE) || '';
  return base + path;
}

const apiState = { csrfToken: null };

async function ensureCsrfToken() {
  if (apiState.csrfToken) return apiState.csrfToken;
  const response = await fetch(apiUrl('/api/csrf'), { credentials: 'include' });
  if (!response.ok) throw new Error('Unable to establish a secure session.');
  const payload = await response.json();
  apiState.csrfToken = payload.csrf_token;
  return apiState.csrfToken;
}

async function apiFetch(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-CSRF-Token', await ensureCsrfToken());
  }

  const response = await fetch(apiUrl(path), {
    ...options,
    method,
    headers,
    credentials: 'include'
  });

  if (response.status === 403 && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    apiState.csrfToken = null;
  }
  return response;
}

// Error Notification System
function showNotification(message, type = 'error', duration = 5000) {
  // Remove any existing notifications
  const existing = document.querySelector('.error-notification');
  if (existing) {
    existing.remove();
  }

  // Create notification element
  const notification = document.createElement('div');
  notification.className = `error-notification ${type}`;
  
  // Icon based on type
  const iconMap = {
    error: 'alert-circle',
    success: 'check-circle',
    warning: 'alert-triangle',
    info: 'info'
  };
  
  const titleMap = {
    error: 'Error',
    success: 'Success',
    warning: 'Warning',
    info: 'Information'
  };

  notification.innerHTML = `
    <div class="error-notification-icon">
      <i data-lucide="${iconMap[type] || 'alert-circle'}" style="width:20px;height:20px;"></i>
    </div>
    <div class="error-notification-content">
      <div class="error-notification-title">${titleMap[type] || 'Notice'}</div>
      <div class="error-notification-message">${message}</div>
    </div>
    <div class="error-notification-close">
      <i data-lucide="x" style="width:16px;height:16px;"></i>
    </div>
  `;

  document.body.appendChild(notification);

  // Initialize Lucide icons
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }

  // Close button handler
  const closeBtn = notification.querySelector('.error-notification-close');
  closeBtn.addEventListener('click', () => {
    notification.style.animation = 'slideOutUp 0.3s ease forwards';
    setTimeout(() => notification.remove(), 300);
  });

  // Auto-dismiss after duration
  if (duration > 0) {
    setTimeout(() => {
      if (notification.parentElement) {
        notification.style.animation = 'slideOutUp 0.3s ease forwards';
        setTimeout(() => notification.remove(), 300);
      }
    }, duration);
  }

  return notification;
}

// Playground Navigation Router - Redirects guest to Registration and logged-in user to Dashboard
function handlePlaygroundNavigation() {
  if (appState.user) {
    switchView('upload');
  } else {
    switchView('auth', 'register');
  }
}

// Global View Switcher
function switchView(viewName, mode) {
  // Auth guard: unauthenticated playground attempts redirect to Registration page
  if (viewName === 'upload' && !appState.user) {
    viewName = 'auth';
    mode = 'register';
  }

  appState.currentView = viewName;
  if (mode) appState.authMode = mode;

  document.querySelectorAll('.page-view').forEach(view => {
    view.classList.remove('active');
  });

  const targetView = document.getElementById(`${viewName}View`);
  if (targetView) {
    targetView.classList.add('active');
    targetView.querySelectorAll('.reveal-on-scroll').forEach(el => el.classList.add('revealed'));
  }

  if (viewName === 'auth') {
    if (typeof updateAuthUI === 'function') updateAuthUI();
  } else if (viewName === 'ocr') {
    setTimeout(() => {
      if (typeof initBidirectionalScrollSync === 'function') initBidirectionalScrollSync();
    }, 100);
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Global App Initialization
document.addEventListener('DOMContentLoaded', () => {
  if (typeof setupScrollReveal === 'function') setupScrollReveal();
  if (typeof setupDashboardEvents === 'function') setupDashboardEvents();
  if (typeof checkAuthStatus === 'function') checkAuthStatus();
});
