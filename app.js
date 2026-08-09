/*
  ================================================================
  UNLIMITED OCR - Full-Stack Single Page Application Engine
  Handles SPA Routing, Auth, SQLite Backend, 3-Panel OCR & Scroll Animations
  ================================================================
*/

if (typeof pdfjsLib !== 'undefined') {
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
}

// Application State
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
  pageBboxes: {},
  pdfDoc: null,
  currentPdfPage: 1,
  totalPages: 1,
  pageImages: [],
  pendingOtpEmail: null,
  otpResendTimer: null
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  setupScrollReveal();
  checkAuthStatus();

  // Re-fit layout text/tables when the window (and thus the panel) resizes
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (appState.currentTab === 'rendered' && document.getElementById('layoutPageCanvas')) {
        fitLayoutBlocks();
      }
    }, 150);
  });
});

// Scroll Reveal Observer
function setupScrollReveal() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
      }
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.reveal-on-scroll').forEach(el => {
    observer.observe(el);
  });
}

// --- SPA VIEW ROUTER ---
function switchView(viewName, mode) {
  appState.currentView = viewName;
  if (mode) appState.authMode = mode;

  document.querySelectorAll('.page-view').forEach(view => {
    view.classList.remove('active');
  });

  const targetView = document.getElementById(`${viewName}View`);
  if (targetView) {
    targetView.classList.add('active');
  }

  if (viewName === 'auth') {
    updateAuthUI();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- AUTHENTICATION SYSTEM ---
async function checkAuthStatus() {
  try {
    const res = await fetch('/api/me');
    if (res.ok) {
      const data = await res.json();
      if (data.authenticated && data.user) {
        setAuthenticatedUser(data.user);
        return;
      }
    }
  } catch (err) {
    console.warn("[Auth] Offline or standalone mode:", err);
  }
  setGuestUser();
}

function setAuthenticatedUser(user) {
  appState.user = user;
  document.getElementById('guestNav').style.display = 'none';
  document.getElementById('userNav').style.display = 'flex';
  document.getElementById('userNameLabel').textContent = user.username;
  document.getElementById('systemStatus').textContent = `Logged in as ${user.username}`;
}

function setGuestUser() {
  appState.user = null;
  document.getElementById('guestNav').style.display = 'flex';
  document.getElementById('userNav').style.display = 'none';
  document.getElementById('systemStatus').textContent = `Engine Ready · SQLite Auth`;
}

function updateAuthUI() {
  const title = document.getElementById('authTitle');
  const subtitle = document.getElementById('authSubtitle');
  const emailGroup = document.getElementById('emailGroup');
  const submitBtn = document.getElementById('authSubmitBtn');
  const toggleText = document.getElementById('authToggleText');
  const toggleLink = document.getElementById('authToggleLink');
  const errorAlert = document.getElementById('authErrorAlert');

  errorAlert.style.display = 'none';

  if (appState.authMode === 'register') {
    title.textContent = 'Create an Account';
    subtitle.textContent = 'Register to store OCR history and documents securely';
    emailGroup.style.display = 'flex';
    submitBtn.textContent = 'Create Account';
    toggleText.textContent = 'Already have an account?';
    toggleLink.textContent = 'Sign In';
  } else {
    title.textContent = 'Welcome Back';
    subtitle.textContent = 'Sign in to access document upload and OCR history';
    emailGroup.style.display = 'none';
    submitBtn.textContent = 'Sign In';
    toggleText.textContent = "Don't have an account?";
    toggleLink.textContent = 'Register';
  }
}

function toggleAuthMode() {
  appState.authMode = appState.authMode === 'login' ? 'register' : 'login';
  updateAuthUI();
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = document.getElementById('authUsername').value.trim();
  const email = document.getElementById('authEmail').value.trim();
  const password = document.getElementById('authPassword').value.trim();
  const errorAlert = document.getElementById('authErrorAlert');
  const submitBtn = document.getElementById('authSubmitBtn');

  errorAlert.style.display = 'none';

  // For login mode, proceed as before.
  if (appState.authMode !== 'register') {
    try {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Signing in...';
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        errorAlert.textContent = data.error || 'Authentication failed';
        errorAlert.style.display = 'block';
        return;
      }
      setAuthenticatedUser(data.user);
      switchView('upload');
    } catch (err) {
      errorAlert.textContent = 'Server communication error';
      errorAlert.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Sign In';
    }
    return;
  }

  // Register mode — send OTP.
  let coldStartTimer = null;
  try {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending verification code...';
    coldStartTimer = setTimeout(() => {
      if (submitBtn && submitBtn.disabled) {
        submitBtn.textContent = 'Waking up server & sending code...';
      }
    }, 4000);

    const res = await fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    });

    if (coldStartTimer) clearTimeout(coldStartTimer);
    const data = await res.json();

    if (!res.ok) {
      errorAlert.textContent = data.error || 'Registration failed. Please try again.';
      errorAlert.style.display = 'block';
      return;
    }
    if (data.status === 'otp_sent') {
      appState.pendingOtpEmail = data.email;
      showOtpSection(data.email);
      if (typeof showNotification === 'function') showNotification(`Verification code sent to ${data.email}`, 'info');
    } else if (data.status === 'success' && data.user) {
      appState.user = data.user;
      appState.authenticated = true;
      if (typeof updateAuthUI === 'function') updateAuthUI();
      if (typeof switchView === 'function') switchView('upload');
      if (typeof showNotification === 'function') showNotification('Account created successfully!', 'success');
    }
  } catch (err) {
    if (coldStartTimer) clearTimeout(coldStartTimer);
    errorAlert.textContent = 'Server connection error. Please try again.';
    errorAlert.style.display = 'block';
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Create Account';
  }
}

// --- OTP VERIFICATION FUNCTIONS ---

function showOtpSection(email) {
  const authForm = document.getElementById('authForm');
  const otpSection = document.getElementById('otpSection');
  const otpEmail = document.getElementById('otpEmailDisplay');
  const authDivider = document.querySelector('.auth-divider');
  const githubBtn = document.getElementById('githubLoginBtn');
  const authFooter = document.querySelector('.auth-footer');

  if (authForm) authForm.style.display = 'none';
  if (authDivider) authDivider.style.display = 'none';
  if (githubBtn) githubBtn.style.display = 'none';
  if (authFooter) authFooter.style.display = 'none';
  if (otpEmail) otpEmail.textContent = email;
  if (otpSection) {
    otpSection.style.display = 'block';
    setTimeout(() => otpSection.classList.add('visible'), 10);
  }

  // Setup OTP input listeners.
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

  // Clear OTP inputs.
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

    input.addEventListener('input', (e) => {
      const val = e.target.value.replace(/[^0-9]/g, '');
      e.target.value = val.charAt(0) || '';
      if (val && idx < inputs.length - 1) {
        inputs[idx + 1].focus();
      }
      // Auto-verify when all 6 digits are entered.
      if (val && idx === inputs.length - 1) {
        const otp = Array.from(inputs).map(i => i.value).join('');
        if (otp.length === 6) handleOtpVerify();
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !e.target.value && idx > 0) {
        inputs[idx - 1].focus();
        inputs[idx - 1].value = '';
      }
    });

    // Handle paste — spread digits across all boxes.
    input.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasted = (e.clipboardData.getData('text') || '').replace(/[^0-9]/g, '').slice(0, 6);
      pasted.split('').forEach((char, i) => {
        if (inputs[i]) inputs[i].value = char;
      });
      if (pasted.length > 0) {
        const focusIdx = Math.min(pasted.length, inputs.length - 1);
        inputs[focusIdx].focus();
      }
      if (pasted.length === 6) handleOtpVerify();
    });
  });

  // Focus the first input.
  if (inputs[0]) inputs[0].focus();
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

    const res = await fetch('/api/verify-otp', {
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
      // Clear inputs on error.
      inputs.forEach(i => { i.value = ''; });
      if (inputs[0]) inputs[0].focus();
      return;
    }

    // Success!
    if (otpSuccess) {
      otpSuccess.textContent = '✓ Account verified successfully! Redirecting...';
      otpSuccess.style.display = 'block';
    }

    setTimeout(() => {
      hideOtpSection();
      setAuthenticatedUser(data.user);
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
    const res = await fetch('/api/resend-otp', {
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
      setTimeout(() => { otpSuccess.style.display = 'none'; }, 4000);
    }
    // Clear old inputs.
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
    await fetch('/api/logout', { method: 'POST' });
  } catch (err) {
    console.warn(err);
  }
  setGuestUser();
  switchView('landing');
}

// --- DASHBOARD & UPLOAD MANAGEMENT ---
function setDashMode(mode) {
  appState.activeDashMode = mode;
  const gundamBtn = document.getElementById('dashGundamBtn');
  const baseBtn = document.getElementById('dashBaseBtn');
  if (gundamBtn) gundamBtn.classList.toggle('active', mode === 'gundam');
  if (baseBtn) baseBtn.classList.toggle('active', mode === 'base');
}

function setupEventListeners() {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');

  if (dropzone && fileInput) {
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('drag-over');
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) {
        processUploadedFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        processUploadedFile(e.target.files[0]);
      }
    });
  }
}

async function loadUserHistory() {
  const historyList = document.getElementById('historyList');
  if (!historyList) return;

  try {
    const res = await fetch('/api/history');
    if (res.ok) {
      const data = await res.json();
      if (data.history && data.history.length > 0) {
        historyList.innerHTML = data.history.map(item => `
          <div class="history-item" onclick="viewHistoryItem('${item.filename}', '${item.mode}', ${item.tokens}, ${item.tps}, ${item.decode_time})">
            <div>
              <div style="font-weight:600;color:var(--text-primary);">${item.filename}</div>
              <div style="font-size:11px;color:var(--text-muted);">${item.mode.toUpperCase()} · ${item.tokens} tokens</div>
            </div>
            <i data-lucide="chevron-right" style="width:16px;height:16px;color:var(--text-muted);"></i>
          </div>
        `).join('');
        lucide.createIcons();
        return;
      }
    }
  } catch (err) {
    console.warn("[History]", err);
  }

  historyList.innerHTML = `<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:40px 0;">No past OCR documents found.</div>`;
}

// --- PDF RENDERING & PREVIEW LOGIC ---
function processUploadedFile(file) {
  appState.currentFile = file;
  appState.pdfDoc = null;
  appState.currentPdfPage = 1;
  appState.pageImages = [];
  appState.pageBboxes = {};

  document.getElementById('ocrDocumentTitle').textContent = `Processing: ${file.name}`;
  document.getElementById('ocrFileBadge').textContent = `${file.name.split('.').pop().toUpperCase()}`;

  const imgElement = document.getElementById('ocrDocumentImg');
  const pageNav = document.getElementById('pdfPageNav');

  if (file.type.includes('pdf') || file.name.toLowerCase().endsWith('.pdf')) {
    pageNav.style.display = 'flex';
    const fileReader = new FileReader();
    fileReader.onload = function () {
      const typedarray = new Uint8Array(this.result);
      if (typeof pdfjsLib !== 'undefined') {
        pdfjsLib.getDocument(typedarray).promise.then(pdf => {
          appState.pdfDoc = pdf;
          appState.totalPages = pdf.numPages;
          renderPdfPage(1);
        }).catch(err => {
          console.warn("[PDF.js Error]", err);
        });
      }
    };
    fileReader.readAsArrayBuffer(file);
  } else {
    pageNav.style.display = 'none';
    const reader = new FileReader();
    reader.onload = (e) => {
      imgElement.src = e.target.result;
    };
    reader.readAsDataURL(file);
  }

  switchView('ocr');
  startLongHorizonOCR();
}

function renderPdfPage(pageNum) {
  if (!appState.pdfDoc) return;
  appState.currentPdfPage = pageNum;
  document.getElementById('pdfPageLabel').textContent = `${pageNum} / ${appState.totalPages}`;

  appState.pdfDoc.getPage(pageNum).then(page => {
    const scale = 1.5;
    const viewport = page.getViewport({ scale: scale });

    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    canvas.height = viewport.height;
    canvas.width = viewport.width;

    const renderContext = {
      canvasContext: context,
      viewport: viewport
    };

    page.render(renderContext).promise.then(() => {
      const dataUrl = canvas.toDataURL('image/png');
      document.getElementById('ocrDocumentImg').src = dataUrl;
      renderBoundingBoxesForPage(pageNum);
      renderLayoutVisualization();
    });
  });
}

function changePdfPage(delta) {
  if (appState.pageImages && appState.pageImages.length > 0) {
    let nextIndex = appState.currentPdfPage - 1 + delta;
    if (nextIndex >= 0 && nextIndex < appState.pageImages.length) {
      appState.currentPdfPage = nextIndex + 1;
      document.getElementById('pdfPageLabel').textContent = `${appState.currentPdfPage} / ${appState.pageImages.length}`;
      document.getElementById('ocrDocumentImg').src = appState.pageImages[nextIndex];
      renderBoundingBoxesForPage(appState.currentPdfPage);
      renderLayoutVisualization();
    }
  } else if (appState.pdfDoc) {
    let nextPage = appState.currentPdfPage + delta;
    if (nextPage >= 1 && nextPage <= appState.totalPages) {
      renderPdfPage(nextPage);
      // renderLayoutVisualization will be called after the PDF page render completes
      setTimeout(() => renderLayoutVisualization(), 150);
    }
  }
}

// --- 3-PANEL GIF-INSPIRED LONG-HORIZON OCR PROCESSING ENGINE ---
async function startLongHorizonOCR() {
  if (appState.isProcessing) return;

  appState.isProcessing = true;
  const laserBeam = document.getElementById('laserScanBeam');
  const bboxContainer = document.getElementById('bboxContainer');
  const rawCodeStream = document.getElementById('rawCodeStream');
  const visualizationContent = document.getElementById('visualizationContent');
  const typewriterCursor = document.getElementById('typewriterCursor');

  laserBeam.classList.add('scanning');
  bboxContainer.innerHTML = '';
  rawCodeStream.innerHTML = '';
  visualizationContent.innerHTML = '';
  typewriterCursor.style.display = 'inline-block';

  let markdownText = '';
  let tokens = 0;
  let tps = 0;
  let latency = 0;

  if (appState.currentFile) {
    try {
      const formData = new FormData();
      formData.append('file', appState.currentFile);
      formData.append('mode', appState.activeDashMode);

      const res = await fetch('/api/ocr', {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        markdownText = data.markdown || '';
        tokens = data.tokens || 0;
        tps = data.tps || 0;
        latency = data.decode_time || 0;
        if (data.page_bboxes && Object.keys(data.page_bboxes).length > 0) {
          appState.pageBboxes = data.page_bboxes;
        }
        if (data.page_images && data.page_images.length > 0) {
          appState.pageImages = data.page_images;
          appState.totalPages = data.pages || data.page_images.length;
          document.getElementById('pdfPageNav').style.display = 'flex';
          document.getElementById('pdfPageLabel').textContent = `1 / ${appState.totalPages}`;
          document.getElementById('ocrDocumentImg').src = data.page_images[0];
        }
      }
    } catch (err) {
      console.warn("[OCR Backend API] Error:", err);
      markdownText = `# OCR Error\n\n*Could not connect to the OCR backend. Please ensure the server is running.*`;
    }
  }

  // Fallback placeholder if no text was extracted
  if (!markdownText || markdownText.trim().length === 0) {
    markdownText = `# No Text Detected\n\n*The OCR engine did not find any recognizable text in the uploaded document. Try a higher-resolution image or check that EasyOCR is installed.*`;
  }

  renderBoundingBoxesForPage(appState.currentPdfPage);
  renderLayoutVisualization();
  stream3PanelTypewriter(markdownText, tokens, tps, latency);
}

function renderBoundingBoxesForPage(pageNum) {
  const container = document.getElementById('bboxContainer');
  container.innerHTML = '';

  let boxes = appState.pageBboxes[pageNum];

  if (!boxes || boxes.length === 0) {
    // Try page 1 as fallback for single-page docs
    boxes = appState.pageBboxes[1] || [];
  }

  if (boxes.length === 0) return;

  boxes.forEach((box, i) => {
    setTimeout(() => {
      const el = document.createElement('div');
      el.className = 'bbox-box ' + (box.type || 'paragraph');
      el.style.left = `${box.x}%`;
      el.style.top = `${box.y}%`;
      el.style.width = `${box.w}%`;
      el.style.height = `${box.h}%`;

      const label = document.createElement('div');
      label.className = 'bbox-label';
      label.textContent = (box.type || 'text').toUpperCase();
      el.appendChild(label);

      container.appendChild(el);
    }, i * 80);
  });
}

// ── Layout Visualization: faithful document structure recreation ────

const BLOCK_COLORS = {
  heading:   { bg: 'rgba(255,255,255,0.12)', border: 'rgba(255,255,255,0.5)' },
  paragraph: { bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.12)' },
  'list-item': { bg: 'rgba(120,180,255,0.08)', border: 'rgba(120,180,255,0.3)' },
  table:     { bg: 'rgba(255,200,100,0.08)', border: 'rgba(255,200,100,0.3)' },
  footer:    { bg: 'rgba(255,255,255,0.02)', border: 'rgba(255,255,255,0.06)' },
  image:     { bg: 'rgba(100,200,255,0.06)', border: 'rgba(100,200,255,0.3)' },
};

function renderLayoutVisualization() {
  const container = document.getElementById('visualizationContent');

  if (appState.currentTab !== 'rendered') return;

  const pageNum = appState.currentPdfPage || 1;
  let blocks = appState.pageBboxes[pageNum];

  if (!blocks || blocks.length === 0) {
    blocks = appState.pageBboxes[1] || [];
  }

  if (blocks.length === 0) {
    // No layout data — show markdown fallback
    const rawText = appState.extractedText || '';
    if (rawText && rawText.trim()) {
      container.innerHTML = `<div style="padding:8px;font-family:var(--font-mono);font-size:11px;line-height:1.6;color:#d4d4d8;white-space:pre-wrap;max-height:480px;overflow-y:auto;">${escapeHtml(rawText)}</div>`;
    } else {
      container.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:40px 0;font-size:13px;">
        <p>Layout visualization will appear here.</p>
        <p style="margin-top:12px;font-size:11px;">The OCR engine analyzes text regions, tables, and structure.</p>
      </div>`;
    }
    return;
  }

  // Determine page aspect ratio from the loaded document image (fall back to A4)
  const docImg = document.getElementById('ocrDocumentImg');
  let aspectRatio = 0.71; // default A4 portrait (w/h)
  if (docImg && docImg.naturalWidth > 0 && docImg.naturalHeight > 0) {
    aspectRatio = docImg.naturalWidth / docImg.naturalHeight;
  }

  // The page canvas fills the panel width; height derives from the aspect ratio.
  let html = `<div class="layout-page" id="layoutPageCanvas" style="
    position:relative;
    width:100%;
    aspect-ratio:${aspectRatio.toFixed(4)};
    background:#0b0b0d;
    border:1px solid var(--border-subtle);
    border-radius:6px;
    overflow:hidden;
    margin:8px auto;
  ">`;

  // Render in document order (top→bottom, then left→right) for faithful stacking
  const sorted = [...blocks].sort((a, b) => {
    const dy = (a.y || 0) - (b.y || 0);
    if (Math.abs(dy) > 1.0) return dy;
    return (a.x || 0) - (b.x || 0);
  });

  sorted.forEach((block, idx) => {
    // ── Image blocks — exact position, exact size ──────────────
    if (block.type === 'image' && block.src) {
      html += `<div class="layout-block layout-block-image" style="
        position:absolute;
        left:${block.x}%;
        top:${block.y}%;
        width:${block.w}%;
        height:${block.h}%;
        background:transparent;
        border-radius:2px;
        overflow:hidden;
        padding:0;
        opacity:0;
        animation:fadeInBlock 0.25s ease ${Math.min(idx * 0.04, 1.2)}s forwards;
        z-index:5;
      " title="Image">
        <img src="${block.src}" style="
          width:100%;height:100%;object-fit:fill;display:block;
        " />
      </div>`;
      return;
    }

    // ── Table blocks — full render, auto-shrink to fit ─────────
    if (block.type === 'table' && block.rows && block.rows.length > 0) {
      const rows = block.rows;
      const headerRow = rows[0] || [];
      const bodyRows = rows.slice(1);
      html += `<div class="layout-block layout-block-table-embedded js-autofit-table" style="
        position:absolute;
        left:${block.x}%;
        top:${block.y}%;
        width:${block.w}%;
        height:${block.h}%;
        background:rgba(255,255,255,0.02);
        border:1px solid rgba(255,255,255,0.12);
        border-radius:2px;
        overflow:hidden;
        padding:0;
        opacity:0;
        animation:fadeInBlock 0.25s ease ${Math.min(idx * 0.04, 1.2)}s forwards;
        z-index:4;
      ">
        <table class="js-fit-target" style="
          width:100%;height:100%;border-collapse:collapse;table-layout:fixed;
          color:var(--text-primary);line-height:1.15;font-size:10px;
        ">
          <thead>
            <tr>${headerRow.map(cell =>
              `<th style="border:1px solid rgba(255,255,255,0.18);padding:1px 3px;
                text-align:left;font-weight:600;background:rgba(255,255,255,0.06);
                overflow:hidden;word-break:break-word;vertical-align:top;">${escapeHtml(cell)}</th>`
            ).join('')}</tr>
          </thead>
          <tbody>
            ${bodyRows.map(row =>
              `<tr>${row.map(cell =>
                `<td style="border:1px solid rgba(255,255,255,0.1);padding:1px 3px;
                  overflow:hidden;word-break:break-word;vertical-align:top;">${escapeHtml(cell)}</td>`
              ).join('')}</tr>`
            ).join('')}
          </tbody>
        </table>
      </div>`;
      return;
    }

    // ── Text-based blocks — true-to-source scale & alignment ───
    const colors = BLOCK_COLORS[block.type] || BLOCK_COLORS.paragraph;
    const text = escapeHtml(block.text || '');
    const align = block.align || 'left';
    const fontWeight = (block.bold || block.type === 'heading') ? '600' : '400';
    const fontStyle = block.italic ? 'italic' : 'normal';
    const zIndex = block.type === 'heading' ? 3 : 1;
    // fontPct is font size as % of page height — resolved to px in the fit pass.
    const fontPct = (typeof block.fontPct === 'number' && block.fontPct > 0)
      ? block.fontPct
      : (block.type === 'heading' ? 2.2 : 1.3);

    html += `<div class="layout-block layout-block-${block.type || 'paragraph'} js-text-block"
      data-font-pct="${fontPct}"
      style="
        position:absolute;
        left:${block.x}%;
        top:${block.y}%;
        width:${block.w}%;
        height:${block.h}%;
        background:${colors.bg};
        border:1px solid ${colors.border};
        border-radius:2px;
        overflow:hidden;
        padding:0 2px;
        font-weight:${fontWeight};
        font-style:${fontStyle};
        text-align:${align};
        color:var(--text-primary);
        line-height:1.15;
        opacity:0;
        animation:fadeInBlock 0.25s ease ${Math.min(idx * 0.04, 1.2)}s forwards;
        cursor:default;
        z-index:${zIndex};
        white-space:pre-wrap;word-break:break-word;
      " title="${block.type}">${text}</div>`;
  });

  html += `</div>`;  // close .layout-page

  // Stats footer
  const headingCount = blocks.filter(b => b.type === 'heading').length;
  const paraCount = blocks.filter(b => b.type === 'paragraph').length;
  const tableCount = blocks.filter(b => (b.type === 'table') && b.rows && b.rows.length > 0).length;
  const listCount = blocks.filter(b => b.type === 'list-item').length;
  const imageCount = blocks.filter(b => b.type === 'image').length;

  html += `<div style="
    margin-top:12px;padding:10px 14px;
    background:var(--bg-tertiary);border-radius:8px;
    border:1px solid var(--border-subtle);
    font-size:11px;color:var(--text-secondary);
    display:flex;flex-wrap:wrap;gap:12px 24px;
  ">
    <span><strong style="color:var(--text-primary);">${blocks.length}</strong> layout items</span>
    ${headingCount > 0 ? `<span><strong style="color:var(--text-primary);">${headingCount}</strong> headings</span>` : ''}
    ${paraCount > 0 ? `<span><strong style="color:var(--text-primary);">${paraCount}</strong> paragraphs</span>` : ''}
    ${tableCount > 0 ? `<span><strong style="color:var(--text-primary);">${tableCount}</strong> tables</span>` : ''}
    ${listCount > 0 ? `<span><strong style="color:var(--text-primary);">${listCount}</strong> list items</span>` : ''}
    ${imageCount > 0 ? `<span><strong style="color:var(--text-primary);">${imageCount}</strong> images</span>` : ''}
    <span style="margin-left:auto;font-family:var(--font-mono);">PyMuPDF + EasyOCR</span>
  </div>`;

  container.innerHTML = html;

  // ── Post-render fit pass: resolve proportional fonts + auto-shrink tables ──
  // Wait for layout to settle so clientHeight/scrollHeight are accurate.
  requestAnimationFrame(() => fitLayoutBlocks());
}

// Resolve proportional font sizes for text blocks and auto-shrink tables/text
// so nothing is cut off inside its positioned box.
function fitLayoutBlocks() {
  const canvas = document.getElementById('layoutPageCanvas');
  if (!canvas) return;
  const pageH = canvas.clientHeight || 0;
  if (pageH <= 0) return;

  // 1) Text blocks: font-size = fontPct% of page pixel height, then shrink to fit
  canvas.querySelectorAll('.js-text-block').forEach(el => {
    const pct = parseFloat(el.getAttribute('data-font-pct')) || 1.3;
    let fontPx = Math.max(3, (pct / 100) * pageH);
    el.style.fontSize = fontPx.toFixed(2) + 'px';

    // Shrink until the text fits within the block's box (min 3px)
    let guard = 0;
    while (
      (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1) &&
      fontPx > 3 && guard < 40
    ) {
      fontPx *= 0.92;
      el.style.fontSize = fontPx.toFixed(2) + 'px';
      guard++;
    }
  });

  // 2) Tables: shrink font until the whole table fits (no rows/cols cut off)
  canvas.querySelectorAll('.js-autofit-table').forEach(box => {
    const table = box.querySelector('.js-fit-target');
    if (!table) return;
    let fontPx = 10;
    table.style.fontSize = fontPx + 'px';

    let guard = 0;
    while (
      (table.scrollHeight > box.clientHeight + 1 || table.scrollWidth > box.clientWidth + 1) &&
      fontPx > 2 && guard < 60
    ) {
      fontPx *= 0.9;
      table.style.fontSize = fontPx.toFixed(2) + 'px';
      guard++;
    }
    // If still overflowing at the minimum, allow internal scroll as a safety net
    if (table.scrollHeight > box.clientHeight + 1 || table.scrollWidth > box.clientWidth + 1) {
      box.style.overflow = 'auto';
    }
  });
}

function stream3PanelTypewriter(fullText, totalTokens, systemTps, decodeLatency) {
  let currentIndex = 0;
  const textLength = fullText.length;
  const startTime = Date.now();

  const rawCodeStream = document.getElementById('rawCodeStream');
  const typewriterCursor = document.getElementById('typewriterCursor');
  const laserBeam = document.getElementById('laserScanBeam');

  const streamInterval = setInterval(() => {
    const chunkSize = Math.floor(Math.random() * 12) + 12;
    currentIndex = Math.min(currentIndex + chunkSize, textLength);
    const currentSub = fullText.substring(0, currentIndex);

    rawCodeStream.textContent = currentSub;
    updateVisualizationPanel(currentSub);

    const elapsedSec = (Date.now() - startTime) / 1000;
    const currentTokens = Math.min(totalTokens, Math.floor(currentIndex / 3.5));

    document.getElementById('metricTokens').textContent = currentTokens;
    document.getElementById('metricTps').textContent = `${systemTps || (currentTokens / elapsedSec).toFixed(1)} t/s`;
    document.getElementById('metricLatency').textContent = `${decodeLatency || elapsedSec.toFixed(2)}s`;

    if (currentIndex >= textLength) {
      clearInterval(streamInterval);
      appState.isProcessing = false;
      laserBeam.classList.remove('scanning');
      typewriterCursor.style.display = 'none';
      appState.extractedText = fullText;
    }
  }, 25);
}

function updateVisualizationPanel(text) {
  const container = document.getElementById('visualizationContent');
  if (appState.currentTab === 'rendered') {
    // Only render markdown during streaming; layout is handled by renderLayoutVisualization
    const pageNum = appState.currentPdfPage || 1;
    const blocks = appState.pageBboxes[pageNum] || appState.pageBboxes[1];
    if (!blocks || blocks.length === 0) {
      container.innerHTML = marked.parse(text || '');
    }
    // When blocks exist, layout was already rendered once — skip during streaming
  } else if (appState.currentTab === 'json') {
    const pageNum = appState.currentPdfPage || 1;
    const blocks = appState.pageBboxes[pageNum] || appState.pageBboxes[1] || [];
    const ast = {
      model: 'baidu/Unlimited-OCR',
      engine: 'easyocr',
      mode: appState.activeDashMode,
      tokens: Math.floor((text || '').length / 3.5),
      total_blocks: blocks.length,
      blocks: blocks.map(b => ({
        id: b.id,
        type: b.type,
        text: (b.text || '').substring(0, 80),
        confidence: b.confidence,
        bbox: { x: b.x, y: b.y, w: b.w, h: b.h }
      }))
    };
    container.innerHTML = `<pre style="color:#a1a1aa;font-family:var(--font-mono);font-size:11px;line-height:1.6;">${JSON.stringify(ast, null, 2)}</pre>`;
  }
}

function switchOutputTab(tab) {
  appState.currentTab = tab;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

  if (tab === 'rendered') document.getElementById('tabRendered').classList.add('active');
  if (tab === 'json') document.getElementById('tabJson').classList.add('active');

  if (tab === 'rendered') {
    renderLayoutVisualization();
  } else {
    updateVisualizationPanel(appState.extractedText || "Processing...");
  }
}

function copyOutputText() {
  navigator.clipboard.writeText(appState.extractedText).then(() => {
    const copyBtn = document.getElementById('copyBtn');
    copyBtn.innerHTML = `<i data-lucide="check" style="width:12px;height:12px;"></i> Copied!`;
    lucide.createIcons();
    setTimeout(() => {
      copyBtn.innerHTML = `<i data-lucide="copy" style="width:12px;height:12px;"></i> Copy`;
      lucide.createIcons();
    }, 2000);
  });
}

function exportMarkdownFile() {
  const blob = new Blob([appState.extractedText], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ocr_output_${Date.now()}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
