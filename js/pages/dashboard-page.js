/*
  ================================================================
  UNLIMITED OCR - Dashboard & File Upload Controller Module
  ================================================================
*/

function setDashMode(mode) {
  appState.activeDashMode = mode;
  const gundamBtn = document.getElementById('dashGundamBtn');
  const baseBtn = document.getElementById('dashBaseBtn');
  if (gundamBtn) gundamBtn.classList.toggle('active', mode === 'gundam');
  if (baseBtn) baseBtn.classList.toggle('active', mode === 'base');
}

function setupDashboardEvents() {
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



function processUploadedFile(file) {
  appState.currentFile = file;
  appState.pdfDoc = null;
  appState.currentPdfPage = 1;
  appState.pageImages = [];

  const docTitle = document.getElementById('ocrDocumentTitle');
  const fileBadge = document.getElementById('ocrFileBadge');
  if (docTitle) docTitle.textContent = `Processing: ${file.name}`;
  if (fileBadge) fileBadge.textContent = `${file.name.split('.').pop().toUpperCase()}`;

  const imgElement = document.getElementById('ocrDocumentImg');
  const pageNav = document.getElementById('pdfPageNav');

  if (file.type.includes('pdf') || file.name.toLowerCase().endsWith('.pdf')) {
    if (pageNav) pageNav.style.display = 'flex';
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
    if (pageNav) pageNav.style.display = 'none';
    const reader = new FileReader();
    reader.onload = (e) => {
      if (imgElement) imgElement.src = e.target.result;
    };
    reader.readAsDataURL(file);
  }

  switchView('ocr');
  setTimeout(() => {
    if (typeof startLongHorizonOCR === 'function') {
      startLongHorizonOCR();
    }
  }, 100);
}
