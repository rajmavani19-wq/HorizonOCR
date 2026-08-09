/*
  ================================================================
  UNLIMITED OCR - Authentication Module (SQLite Backend)
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
    if (submitBtn) submitBtn.textContent = 'Create Account';
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

  // Login Mode — direct authentication
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
      await checkAuthStatus();
      switchView('upload');
    } catch (err) {
      if (errorAlert) {
        errorAlert.textContent = 'Server communication error';
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

  // Register Mode — client validation first
  if (!/^[^@\s]+@gmail\.com$/i.test(email)) {
    if (errorAlert) {
      errorAlert.textContent = 'Registration is only allowed with a @gmail.com email address.';
      errorAlert.style.display = 'block';
    }
    return;
  }

  // Send OTP request to backend
  let coldStartTimer = null;
  try {
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending verification code...';
      coldStartTimer = setTimeout(() => {
        if (submitBtn && submitBtn.disabled) {
          submitBtn.textContent = 'Waking up server & sending code...';
        }
      }, 4000);
    }
    const res = await apiFetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    });

    if (coldStartTimer) clearTimeout(coldStartTimer);
    const data = await res.json();

    if (!res.ok) {
      if (errorAlert) {
        errorAlert.textContent = data.error || 'Registration failed. Please try again.';
        errorAlert.style.display = 'block';
      }
      return;
    }

    if (data.status === 'otp_sent') {
      appState.pendingOtpEmail = data.email;
      showOtpSection(data.email);
      if (typeof showNotification === 'function') showNotification(`Verification code sent to ${data.email}`, 'info');
    }
  } catch (err) {
    if (coldStartTimer) clearTimeout(coldStartTimer);
    if (errorAlert) {
      errorAlert.textContent = 'Server connection error. Please try again.';
      errorAlert.style.display = 'block';
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Account';
    }
  }
}

// ── OTP Verification Flow ──────────────────────────────────────────────────

function showOtpSection(email) {
  const authForm = document.getElementById('authForm');
  const otpSection = document.getElementById('otpSection');
  const otpEmail = document.getElementById('otpEmailDisplay');
  const authDivider = document.querySelector('.auth-divider');
  const githubBtn = document.getElementById('githubLoginBtn');
  const authFooter = document.querySelector('.auth-footer');
  const errorAlert = document.getElementById('authErrorAlert');

  if (errorAlert) errorAlert.style.display = 'none';
  if (authForm) authForm.style.display = 'none';
  if (authDivider) authDivider.style.display = 'none';
  if (githubBtn) githubBtn.style.display = 'none';
  if (authFooter) authFooter.style.display = 'none';
  if (otpEmail) otpEmail.textContent = email;
  if (otpSection) {
    otpSection.style.display = 'block';
    setTimeout(() => otpSection.classList.add('visible'), 10);
  }

  setupOtpInputs();
  startResendCooldown();
}

function hideOtpSection() {
  const authForm = document.getElementById('authForm');
  const otpSection = document.getElementById('otpSection');
  const authDivider = document.querySelector('.auth-divider');
  const githubBtn = document.getElementById('githubLoginBtn');
  const authFooter = document.querySelector('.auth-footer');
  const otpError = document.getElementById('otpErrorAlert');
  const otpSuccess = document.getElementById('otpSuccessAlert');

  if (authForm) authForm.style.display = '';
  if (authDivider) authDivider.style.display = '';
  if (githubBtn) githubBtn.style.display = '';
  if (authFooter) authFooter.style.display = '';
  if (otpSection) {
    otpSection.classList.remove('visible');
    otpSection.style.display = 'none';
  }
  if (otpError) otpError.style.display = 'none';
  if (otpSuccess) otpSuccess.style.display = 'none';

  document.querySelectorAll('.otp-digit').forEach(input => { input.value = ''; });
  appState.pendingOtpEmail = null;
  if (appState.otpResendTimer) {
    clearInterval(appState.otpResendTimer);
    appState.otpResendTimer = null;
  }
}

function setupOtpInputs() {
  const inputs = document.querySelectorAll('.otp-digit');
  inputs.forEach((input, idx) => {
    input.value = '';

    // Remove existing event handlers by cloning if needed
    const newInput = input.cloneNode(true);
    input.parentNode.replaceChild(newInput, input);
  });

  const refreshedInputs = document.querySelectorAll('.otp-digit');
  refreshedInputs.forEach((input, idx) => {
    input.addEventListener('input', (e) => {
      const val = e.target.value.replace(/[^0-9]/g, '');
      e.target.value = val.charAt(0) || '';
      if (val && idx < refreshedInputs.length - 1) {
        refreshedInputs[idx + 1].focus();
      }
      if (val && idx === refreshedInputs.length - 1) {
        const otp = Array.from(refreshedInputs).map(i => i.value).join('');
        if (otp.length === 6) handleOtpVerify();
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !e.target.value && idx > 0) {
        refreshedInputs[idx - 1].focus();
        refreshedInputs[idx - 1].value = '';
      }
    });

    input.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasted = (e.clipboardData.getData('text') || '').replace(/[^0-9]/g, '').slice(0, 6);
      pasted.split('').forEach((char, i) => {
        if (refreshedInputs[i]) refreshedInputs[i].value = char;
      });
      if (pasted.length > 0) {
        const focusIdx = Math.min(pasted.length, refreshedInputs.length - 1);
        refreshedInputs[focusIdx].focus();
      }
      if (pasted.length === 6) handleOtpVerify();
    });
  });

  if (refreshedInputs[0]) refreshedInputs[0].focus();
}

async function handleOtpVerify() {
  const inputs = document.querySelectorAll('.otp-digit');
  const otp = Array.from(inputs).map(i => i.value).join('');
  const otpError = document.getElementById('otpErrorAlert');
  const otpSuccess = document.getElementById('otpSuccessAlert');
  const verifyBtn = document.getElementById('otpVerifyBtn');

  if (otpError) otpError.style.display = 'none';
  if (otpSuccess) otpSuccess.style.display = 'none';

  if (otp.length !== 6) {
    if (otpError) {
      otpError.textContent = 'Please enter the complete 6-digit code.';
      otpError.style.display = 'block';
    }
    return;
  }

  try {
    if (verifyBtn) {
      verifyBtn.disabled = true;
      verifyBtn.textContent = 'Verifying...';
    }

    const res = await apiFetch('/api/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: appState.pendingOtpEmail, otp })
    });

    const data = await res.json();

    if (!res.ok) {
      if (otpError) {
        otpError.textContent = data.error || 'Verification failed';
        otpError.style.display = 'block';
      }
      inputs.forEach(i => { i.value = ''; });
      if (inputs[0]) inputs[0].focus();
      return;
    }

    // Success
    if (otpSuccess) {
      otpSuccess.textContent = '✓ Account verified successfully! Redirecting...';
      otpSuccess.style.display = 'block';
    }

    setTimeout(async () => {
      hideOtpSection();
      await checkAuthStatus();
      switchView('upload');
    }, 1200);
  } catch (err) {
    if (otpError) {
      otpError.textContent = 'Server communication error';
      otpError.style.display = 'block';
    }
  } finally {
    if (verifyBtn) {
      verifyBtn.disabled = false;
      verifyBtn.textContent = 'Verify & Create Account';
    }
  }
}

function startResendCooldown() {
  const resendLink = document.getElementById('otpResendLink');
  const resendTimer = document.getElementById('otpResendTimer');
  const resendText = document.getElementById('otpResendText');

  let countdown = 60;
  if (resendLink) resendLink.style.display = 'none';
  if (resendText) resendText.style.display = '';
  if (resendTimer) {
    resendTimer.style.display = '';
    resendTimer.textContent = `Resend available in ${countdown}s`;
  }

  if (appState.otpResendTimer) clearInterval(appState.otpResendTimer);

  appState.otpResendTimer = setInterval(() => {
    countdown--;
    if (resendTimer) resendTimer.textContent = `Resend available in ${countdown}s`;
    if (countdown <= 0) {
      clearInterval(appState.otpResendTimer);
      appState.otpResendTimer = null;
      if (resendTimer) resendTimer.style.display = 'none';
      if (resendLink) resendLink.style.display = '';
    }
  }, 1000);
}

async function handleResendOtp() {
  const otpError = document.getElementById('otpErrorAlert');
  const otpSuccess = document.getElementById('otpSuccessAlert');
  const resendLink = document.getElementById('otpResendLink');

  if (otpError) otpError.style.display = 'none';

  if (!appState.pendingOtpEmail) {
    if (otpError) {
      otpError.textContent = 'No pending registration. Please go back and try again.';
      otpError.style.display = 'block';
    }
    return;
  }

  try {
    if (resendLink) resendLink.style.display = 'none';
    const res = await apiFetch('/api/resend-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: appState.pendingOtpEmail })
    });
    const data = await res.json();
    if (!res.ok) {
      if (otpError) {
        otpError.textContent = data.error || 'Failed to resend code';
        otpError.style.display = 'block';
      }
      if (resendLink) resendLink.style.display = '';
      return;
    }
    if (otpSuccess) {
      otpSuccess.textContent = '✓ A new verification code has been sent!';
      otpSuccess.style.display = 'block';
      setTimeout(() => { if (otpSuccess) otpSuccess.style.display = 'none'; }, 4000);
    }
    document.querySelectorAll('.otp-digit').forEach(i => { i.value = ''; });
    const firstInput = document.querySelector('.otp-digit');
    if (firstInput) firstInput.focus();
    startResendCooldown();
  } catch (err) {
    if (otpError) {
      otpError.textContent = 'Server communication error';
      otpError.style.display = 'block';
    }
    if (resendLink) resendLink.style.display = '';
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
  // Top-level navigation is required: the backend 302-redirects to GitHub,
  // so this cannot be performed with fetch().
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

  // Remove the callback query string so a page refresh does not replay the toast.
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
