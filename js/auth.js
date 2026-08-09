/*
  ================================================================
  UNLIMITED OCR - Authentication Module (Direct SQLite Auth)
  ================================================================
*/

async function checkAuthStatus() {
  try {
    const res = await apiFetch('/api/me');
    if (res.ok) {
      const data = await res.json();
      apiState.csrfToken = data.csrf_token || null;
      if (data.authenticated && data.user) {
        setAuthenticatedUser(data.user);
        return;
      }
    }
  } catch (err) {
    console.warn('[Auth] Session check failed:', err);
  }
  setGuestUser();
}

function setAuthenticatedUser(user) {
  appState.user = user;
  const guestNav = document.getElementById('guestNav');
  const userNav = document.getElementById('userNav');
  const userNameLabel = document.getElementById('userNameLabel');
  const systemStatus = document.getElementById('systemStatus');

  if (guestNav) guestNav.style.display = 'none';
  if (userNav) userNav.style.display = 'flex';
  if (userNameLabel) userNameLabel.textContent = user.username;
  if (systemStatus) systemStatus.textContent = `Logged in as ${user.username}`;
}

function setGuestUser() {
  appState.user = null;
  const guestNav = document.getElementById('guestNav');
  const userNav = document.getElementById('userNav');
  const systemStatus = document.getElementById('systemStatus');

  if (guestNav) guestNav.style.display = 'flex';
  if (userNav) userNav.style.display = 'none';
  if (systemStatus) systemStatus.textContent = `Engine Ready · SQLite Auth`;
}

function updateAuthUI() {
  const title = document.getElementById('authTitle');
  const subtitle = document.getElementById('authSubtitle');
  const emailGroup = document.getElementById('emailGroup');
  const submitBtn = document.getElementById('authSubmitBtn');
  const toggleText = document.getElementById('authToggleText');
  const toggleLink = document.getElementById('authToggleLink');
  const errorAlert = document.getElementById('authErrorAlert');

  if (errorAlert) errorAlert.style.display = 'none';

  if (appState.authMode === 'register') {
    if (title) title.textContent = 'Create an Account';
    if (subtitle) subtitle.textContent = 'Register to store OCR history and documents securely';
    if (emailGroup) emailGroup.style.display = 'flex';
    if (submitBtn) submitBtn.textContent = 'Create Account & Sign In';
    if (toggleText) toggleText.textContent = 'Already have an account?';
    if (toggleLink) toggleLink.textContent = 'Sign In';
  } else {
    if (title) title.textContent = 'Welcome Back';
    if (subtitle) subtitle.textContent = 'Sign in to access document upload and OCR history';
    if (emailGroup) emailGroup.style.display = 'none';
    if (submitBtn) submitBtn.textContent = 'Sign In';
    if (toggleText) toggleText.textContent = "Don't have an account?";
    if (toggleLink) toggleLink.textContent = 'Register';
  }
}

function toggleAuthMode() {
  appState.authMode = appState.authMode === 'login' ? 'register' : 'login';
  updateAuthUI();
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = document.getElementById('authUsername').value.trim();
  const email = document.getElementById('authEmail') ? document.getElementById('authEmail').value.trim() : '';
  const password = document.getElementById('authPassword').value.trim();
  const errorAlert = document.getElementById('authErrorAlert');
  const submitBtn = document.getElementById('authSubmitBtn');

  if (errorAlert) errorAlert.style.display = 'none';

  // ── Login Mode ──
  if (appState.authMode !== 'register') {
    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';
      }
      const res = await apiFetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        if (errorAlert) {
          errorAlert.textContent = data.error || 'Authentication failed';
          errorAlert.style.display = 'block';
        }
        return;
      }
      showNotification(`Welcome back, ${data.user ? data.user.username : username}!`, 'success');
      await checkAuthStatus();
      switchView('upload');
    } catch (err) {
      if (errorAlert) {
        errorAlert.textContent = 'Server communication error. Please try again.';
        errorAlert.style.display = 'block';
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign In';
      }
    }
    return;
  }

  // ── Register Mode ──
  if (!username || username.length < 3) {
    if (errorAlert) {
      errorAlert.textContent = 'Username must be at least 3 characters.';
      errorAlert.style.display = 'block';
    }
    return;
  }

  if (!email || !/^[^@\s]+@gmail\.com$/i.test(email)) {
    if (errorAlert) {
      errorAlert.textContent = 'Registration is only allowed with a @gmail.com email address.';
      errorAlert.style.display = 'block';
    }
    return;
  }

  if (!password || password.length < 6) {
    if (errorAlert) {
      errorAlert.textContent = 'Password must be at least 6 characters.';
      errorAlert.style.display = 'block';
    }
    return;
  }

  // Direct registration & login
  try {
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating Account...';
    }
    const res = await apiFetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    });

    const data = await res.json();
    if (!res.ok) {
      if (errorAlert) {
        errorAlert.textContent = data.error || 'Registration failed';
        errorAlert.style.display = 'block';
      }
      return;
    }

    showNotification('Account created successfully! Welcome to HorizonOCR.', 'success');
    await checkAuthStatus();
    switchView('upload');
  } catch (err) {
    if (errorAlert) {
      errorAlert.textContent = 'Server communication error. Please try again.';
      errorAlert.style.display = 'block';
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Account & Sign In';
    }
  }
}

async function handleLogout() {
  try {
    await apiFetch('/api/logout', { method: 'POST' });
  } catch (err) {
    console.warn('[Auth] Logout request failed:', err);
  }
  apiState.csrfToken = null;
  setGuestUser();
  switchView('landing');
}

// ── GitHub OAuth ─────────────────────────────────────────────────────────

function startGithubLogin() {
  window.location.href = apiUrl('/api/auth/github/login');
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

async function handleGithubCallback() {
  const params = new URLSearchParams(window.location.search);
  const status = params.get('github_auth');
  if (!status) return;

  if (window.history && window.history.replaceState) {
    window.history.replaceState({}, '', window.location.pathname);
  }

  if (status === 'success') {
    showNotification('Signed in with GitHub. Welcome to HorizonOCR!', 'success');
    await checkAuthStatus();
    if (appState.user) {
      switchView('upload');
    } else {
      switchView('auth', 'login');
    }
  } else {
    const message = escapeHtml(params.get('msg') || 'GitHub sign-in could not be completed. Please try again.');
    showNotification(message, 'error', 8000);
    switchView('auth', 'login');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (typeof handleGithubCallback === 'function') handleGithubCallback();
});
