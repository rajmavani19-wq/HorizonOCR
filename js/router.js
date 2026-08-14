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
  ocrSpeed: 'medium',
  pendingOtpEmail: null,
  otpResendTimer: null
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

// Contact Form Submission Handler (Persists to SQLite Database)
async function handleContactSubmit(event) {
  if (event) event.preventDefault();
  const name = document.getElementById('contactName')?.value?.trim();
  const email = document.getElementById('contactEmail')?.value?.trim();
  const subject = document.getElementById('contactSubject')?.value || 'General Platform Inquiry';
  const message = document.getElementById('contactMessage')?.value?.trim();
  const submitBtn = event?.target?.querySelector('button[type="submit"]');

  if (!name || !email || !message) {
    showNotification('Please fill in all required fields.', 'warning');
    return;
  }

  const originalBtnText = submitBtn ? submitBtn.innerHTML : '';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner" style="display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:8px;"></span> Submitting...';
  }

  try {
    const res = await apiFetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, subject, message })
    });

    const data = await res.json();
    if (!res.ok) {
      showNotification(data.error || 'Failed to submit inquiry. Please try again.', 'error');
      return;
    }

    showNotification(data.message || ('Thank you! Your inquiry #' + data.inquiry_id + ' has been saved in our system. Our engineering team will contact you shortly.'), 'success', 7000);
    const form = document.getElementById('contactForm');
    if (form) form.reset();
  } catch (err) {
    console.error('[Contact Form] Submission error:', err);
    showNotification('Network communication error. Please check your connection and try again.', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalBtnText;
    }
  }
}

// Interactive FAQ Accordion Toggle
function toggleFaq(questionEl) {
  const item = questionEl.closest('.faq-item');
  if (!item) return;
  const wasOpen = item.classList.contains('open');
  
  // Close all other items in the same list
  const list = item.closest('.faq-list');
  if (list) {
    list.querySelectorAll('.faq-item').forEach(el => el.classList.remove('open'));
  }

  // Toggle current
  if (!wasOpen) {
    item.classList.add('open');
  }
}

// Copy Contact Email to Clipboard with instant feedback
function copyContactEmail(emailText, btnEl) {
  if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(emailText).then(() => {
      showCopiedFeedback(btnEl);
    }).catch(() => {
      fallbackCopyText(emailText, btnEl);
    });
  } else {
    fallbackCopyText(emailText, btnEl);
  }
}

function showCopiedFeedback(btnEl) {
  if (!btnEl) return;
  const originalHTML = btnEl.innerHTML;
  btnEl.classList.add('copied');
  btnEl.innerHTML = '<i data-lucide="check" style="width:12px;height:12px;"></i> Copied!';
  if (typeof lucide !== 'undefined') lucide.createIcons();

  showNotification('Copied email to clipboard: ' + btnEl.previousElementSibling?.querySelector('div:last-child')?.textContent || 'Email copied', 'info', 3000);

  setTimeout(() => {
    btnEl.classList.remove('copied');
    btnEl.innerHTML = originalHTML;
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }, 2000);
}

function fallbackCopyText(text, btnEl) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.select();
  try {
    document.execCommand('copy');
    showCopiedFeedback(btnEl);
  } catch (err) {
    showNotification('Unable to copy text: ' + text, 'warning');
  }
  document.body.removeChild(textArea);
}

// Global App Initialization
document.addEventListener('DOMContentLoaded', () => {
  if (typeof setupScrollReveal === 'function') setupScrollReveal();
  if (typeof setupDashboardEvents === 'function') setupDashboardEvents();
  if (typeof checkAuthStatus === 'function') checkAuthStatus();
});
