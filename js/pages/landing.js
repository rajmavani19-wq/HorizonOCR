/*
  ================================================================
  UNLIMITED OCR - Landing Page Controller Module
  ================================================================
*/

function setupScrollReveal() {
  const revealItems = document.querySelectorAll('.reveal-on-scroll');

  if (!('IntersectionObserver' in window)) {
    revealItems.forEach(el => el.classList.add('revealed'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });

  revealItems.forEach(el => observer.observe(el));
}

function copySetupCommand(button) {
  const command = 'python -m venv .venv\n# Windows: .venv\\Scripts\\activate\n# macOS/Linux: source .venv/bin/activate\npip install -r requirements.txt\npython server.py';
  const original = button.innerHTML;

  const markCopied = () => {
    button.innerHTML = '<i data-lucide="check"></i> Copied';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    window.setTimeout(() => {
      button.innerHTML = original;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }, 1800);
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(command).then(markCopied).catch(() => window.prompt('Copy the command:', command));
  } else {
    window.prompt('Copy the command:', command);
  }
}
