/*
  ================================================================
  UNLIMITED OCR - 3-Panel Workspace Engine Controller Module
  ================================================================
*/

function renderPdfPage(pageNum) {
  if (!appState.pdfDoc) return;
  appState.currentPdfPage = pageNum;
  appState.totalPages = appState.pdfDoc.numPages;
  const pageLabel = document.getElementById('pdfPageLabel');
  if (pageLabel) pageLabel.textContent = `${pageNum} / ${appState.totalPages}`;

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
      const imgEl = document.getElementById('ocrDocumentImg');
      if (imgEl) imgEl.src = dataUrl;
    });
  });
}

function changePdfPage(delta) {
  let nextPage = appState.currentPdfPage + delta;
  if (appState.pdfDoc) {
    if (nextPage >= 1 && nextPage <= appState.pdfDoc.numPages) {
      renderPdfPage(nextPage);
    }
  } else if (appState.pageImages && appState.pageImages.length > 0) {
    if (nextPage >= 1 && nextPage <= appState.pageImages.length) {
      appState.currentPdfPage = nextPage;
      appState.totalPages = appState.pageImages.length;
      const pageLabel = document.getElementById('pdfPageLabel');
      const imgEl = document.getElementById('ocrDocumentImg');
      if (pageLabel) pageLabel.textContent = `${nextPage} / ${appState.pageImages.length}`;
      if (imgEl) imgEl.src = appState.pageImages[nextPage - 1];
    }
  }
}

function countWords(str) {
  if (!str) return 0;
  return str.trim().split(/\s+/).filter(Boolean).length;
}

function loadHistoryIntoOCRWorkspace(doc) {
  const laserBeam = document.getElementById('laserScanBeam');
  const rawCodeStream = document.getElementById('rawCodeStream');
  const typewriterCursor = document.getElementById('typewriterCursor');

  if (laserBeam) laserBeam.classList.remove('scanning');
  if (typewriterCursor) typewriterCursor.style.display = 'none';

  if (rawCodeStream) rawCodeStream.textContent = doc.markdown;
  updateVisualizationPanel(doc.markdown);

  const tokenEl = document.getElementById('metricTokens');
  const tpsEl = document.getElementById('metricTps');
  const latencyEl = document.getElementById('metricLatency');
  const confContainer = document.getElementById('metricConfidenceContainer');

  if (tokenEl) tokenEl.textContent = doc.tokens;
  if (tpsEl) tpsEl.textContent = `${doc.tps} t/s`;
  if (latencyEl) latencyEl.textContent = `${doc.decode_time}s`;
  if (confContainer) confContainer.style.display = 'flex';
}

function updateOcrControlState(isProcessing) {
  const startBtn = document.getElementById('startOcrBtn');
  const stopBtn = document.getElementById('stopOcrBtn');
  if (startBtn) startBtn.disabled = isProcessing;
  if (stopBtn) stopBtn.disabled = !isProcessing;
}

function updateOcrSpeed(speed) {
  if (['low', 'medium', 'fast'].includes(speed)) {
    appState.ocrSpeed = speed;
  }
}

function stopLongHorizonOCR() {
  if (appState.ocrAbortController) {
    appState.ocrAbortController.abort();
    appState.ocrAbortController = null;
  }
  if (appState.ocrStreamTimer) {
    clearInterval(appState.ocrStreamTimer);
    appState.ocrStreamTimer = null;
  }

  appState.isProcessing = false;
  const laserBeam = document.getElementById('laserScanBeam');
  const typewriterCursor = document.getElementById('typewriterCursor');
  if (laserBeam) laserBeam.classList.remove('scanning');
  if (typewriterCursor) typewriterCursor.style.display = 'none';
  updateOcrControlState(false);
}

async function startLongHorizonOCR() {
  if (appState.isProcessing || !appState.currentFile) return;

  appState.isProcessing = true;
  appState.ocrAbortController = new AbortController();
  updateOcrControlState(true);
  const laserBeam = document.getElementById('laserScanBeam');
  const rawCodeStream = document.getElementById('rawCodeStream');
  const visualizationContent = document.getElementById('visualizationContent');
  const typewriterCursor = document.getElementById('typewriterCursor');

  if (laserBeam) laserBeam.classList.add('scanning');
  if (rawCodeStream) rawCodeStream.textContent = '';
  if (visualizationContent) visualizationContent.innerHTML = '';
  if (typewriterCursor) typewriterCursor.style.display = 'inline-block';
  const speedSelector = document.getElementById('speedSelector');
  if (speedSelector) speedSelector.value = appState.ocrSpeed;

  // Reset metrics
  const tokenEl = document.getElementById('metricTokens');
  const tpsEl = document.getElementById('metricTps');
  const latencyEl = document.getElementById('metricLatency');
  const confContainer = document.getElementById('metricConfidenceContainer');

  if (tokenEl) tokenEl.textContent = '0';
  if (tpsEl) tpsEl.textContent = '0.0 t/s';
  if (latencyEl) latencyEl.textContent = '0.00s';
  if (confContainer) confContainer.style.display = 'none';

  let markdownText = '';
  let tokens = 0;
  let tps = 0;
  let latency = 0;
  let apiSucceeded = false;

  if (appState.currentFile) {
    try {
      const formData = new FormData();
      formData.append('file', appState.currentFile);
      formData.append('mode', appState.activeDashMode);

      const res = await apiFetch('/api/ocr', {
        method: 'POST',
        body: formData,
        signal: appState.ocrAbortController.signal
      });

      if (res.ok) {
        const data = await res.json();
        if (data.markdown && data.markdown.trim()) {
          markdownText = data.markdown;
          apiSucceeded = true;
        }
        tokens = data.tokens || 0;
        tps = data.tps || 0;
        latency = data.decode_time || 0;
        
        // Store page_bboxes for layout visualization
        if (data.page_bboxes) {
          appState.pageBboxes = data.page_bboxes;
        }
        
        if (data.page_images && data.page_images.length > 0) {
          appState.pageImages = data.page_images;
          if (appState.pdfDoc) {
            appState.totalPages = appState.pdfDoc.numPages;
          } else {
            appState.totalPages = data.pages || data.page_images.length;
          }
          const pageNav = document.getElementById('pdfPageNav');
          const pageLabel = document.getElementById('pdfPageLabel');
          const imgEl = document.getElementById('ocrDocumentImg');
          if (pageNav) pageNav.style.display = 'flex';
          if (pageLabel) pageLabel.textContent = `${appState.currentPdfPage} / ${appState.totalPages}`;
          if (imgEl && !appState.pdfDoc) imgEl.src = data.page_images[0];
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        const errorMsg = errorData.error || `Server error: ${res.status}`;
        if (typeof showNotification === 'function') {
          showNotification(errorMsg, 'error');
        }
        console.warn("[OCR] Server returned error:", res.status, errorMsg);
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      if (typeof showNotification === 'function') {
        showNotification('Failed to connect to OCR service. Please check your connection and try again.', 'error');
      }
      console.warn("[OCR Backend API] Connection failed:", err);
    }
  }

  if (!appState.isProcessing) return;

  if (!apiSucceeded || !markdownText) {
    // Show a meaningful error in the raw output stream
    markdownText = '# Processing Notice\n\nThe OCR engine was unable to process this document. Please check that the file is a valid PDF or PNG and try again.';
    tokens = 0;
    tps = 0;
    latency = 0;
    if (rawCodeStream) rawCodeStream.style.color = '#f87171';
  } else if (rawCodeStream) {
    rawCodeStream.style.color = '';
  }

  stream3PanelTypewriter(markdownText, tokens, tps, latency);
}

function changePdfPageTo(pageNum) {
  if (pageNum < 1 || pageNum > appState.totalPages) return;
  appState.currentPdfPage = pageNum;
  const pageLabel = document.getElementById('pdfPageLabel');
  if (pageLabel) pageLabel.textContent = `${pageNum} / ${appState.totalPages}`;

  if (appState.pdfDoc) {
    renderPdfPage(pageNum);
  } else if (appState.pageImages && appState.pageImages.length >= pageNum) {
    const imgEl = document.getElementById('ocrDocumentImg');
    if (imgEl) imgEl.src = appState.pageImages[pageNum - 1];
  }
  
  // Update layout visualization for the new page
  updateVisualizationPanel(appState.extractedText || '');
  
  // Update bounding boxes for the new page
  renderBoundingBoxesForPage(pageNum);
}

// Speed presets: both the tick interval AND the characters-per-tick scale
// with speed, so the effective reveal rate differs by roughly 25x between
// "low" and "fast" — a difference that is clearly visible regardless of
// document length (a paragraph-count-based cadence made short documents
// look identical across all three speeds).
const OCR_SPEED_PRESETS = {
  low:    { interval: 55, minChunk: 5,  maxChunk: 12 },
  medium: { interval: 26, minChunk: 14, maxChunk: 24 },
  fast:   { interval: 10, minChunk: 30, maxChunk: 55 }
};

let isSyncingPanelScroll = false;

function initBidirectionalScrollSync() {
  const rawCodeStream = document.getElementById('rawCodeStream');
  const visualizationContent = document.getElementById('visualizationContent');

  if (!rawCodeStream || !visualizationContent) return;

  const p2 = rawCodeStream.parentElement;
  const p3 = visualizationContent.parentElement;

  if (!p2 || !p3 || p2.dataset.scrollSyncBound) return;
  p2.dataset.scrollSyncBound = 'true';

  const syncScroll = (source, target) => {
    if (isSyncingPanelScroll || appState.isProcessing) return;
    isSyncingPanelScroll = true;

    const sourceMax = source.scrollHeight - source.clientHeight;
    const targetMax = target.scrollHeight - target.clientHeight;

    if (sourceMax > 0 && targetMax > 0) {
      const ratio = source.scrollTop / sourceMax;
      target.scrollTop = Math.round(ratio * targetMax);
    }

    requestAnimationFrame(() => {
      isSyncingPanelScroll = false;
    });
  };

  p2.addEventListener('scroll', () => syncScroll(p2, p3), { passive: true });
  p3.addEventListener('scroll', () => syncScroll(p3, p2), { passive: true });
}

function stream3PanelTypewriter(fullText, totalTokens, systemTps, decodeLatency) {
  const rawCodeStream = document.getElementById('rawCodeStream');
  const typewriterCursor = document.getElementById('typewriterCursor');
  const laserBeam = document.getElementById('laserScanBeam');
  const visualizationContent = document.getElementById('visualizationContent');

  initBidirectionalScrollSync();

  const finalizeStream = () => {
    appState.isProcessing = false;
    appState.ocrAbortController = null;
    appState.ocrStreamTimer = null;
    appState.extractedText = fullText;
    if (laserBeam) laserBeam.classList.remove('scanning');
    if (typewriterCursor) typewriterCursor.style.display = 'none';
    updateOcrControlState(false);

    // Make sure the visualization panel is updated with full rendered content
    updateVisualizationPanel(fullText);

    // Show confidence metric container when visualization process is completed
    const confContainer = document.getElementById('metricConfidenceContainer');
    if (confContainer) confContainer.style.display = 'flex';
  };

  if (!rawCodeStream || !fullText) {
    if (rawCodeStream) rawCodeStream.textContent = fullText || '';
    finalizeStream();
    return;
  }

  const textLength = fullText.length;
  const preset = OCR_SPEED_PRESETS[appState.ocrSpeed] || OCR_SPEED_PRESETS.medium;

  let currentIndex = 0;
  const tokenEl = document.getElementById('metricTokens');
  const tpsEl = document.getElementById('metricTps');
  const latencyEl = document.getElementById('metricLatency');
  const startTime = Date.now();

  const streamTimer = setInterval(() => {
    const chunkSize = preset.minChunk + Math.floor(Math.random() * (preset.maxChunk - preset.minChunk + 1));
    currentIndex = Math.min(currentIndex + chunkSize, textLength);
    const currentText = fullText.substring(0, currentIndex);
    rawCodeStream.textContent = currentText;

    // Auto-detect active page from `## Page N` markers
    const pageMatches = currentText.match(/## Page (\d+)/g);
    if (pageMatches && pageMatches.length > 0) {
      const lastMatch = pageMatches[pageMatches.length - 1];
      const activePage = parseInt(lastMatch.replace('## Page ', ''), 10);
      if (activePage && activePage !== appState.currentPdfPage && activePage <= appState.totalPages) {
        changePdfPageTo(activePage);
      }
    }

    // Update live visualization
    updateVisualizationPanel(currentText);

    // Instant 0ms lockstep scroll sync for Panel 2 & Panel 3 on every frame
    requestAnimationFrame(() => {
      const p2 = rawCodeStream.parentElement;
      const p3 = visualizationContent ? visualizationContent.parentElement : null;
      if (p2) {
        p2.scrollTop = p2.scrollHeight;
      }
      if (p3) {
        p3.scrollTop = p3.scrollHeight;
      }
    });

    // Live metrics based on proportion revealed
    const proportion = currentIndex / textLength;
    const currentTokens = Math.floor(totalTokens * proportion);
    const elapsedSec = Math.max((Date.now() - startTime) / 1000, 0.1);
    if (tokenEl) tokenEl.textContent = currentTokens;
    if (tpsEl) tpsEl.textContent = systemTps > 0 ? `${systemTps} t/s` : `${(currentTokens / elapsedSec).toFixed(1)} t/s`;
    if (latencyEl && decodeLatency > 0) latencyEl.textContent = `${decodeLatency}s`;

    if (currentIndex >= textLength) {
      clearInterval(streamTimer);
      finalizeStream();

      // Show final accurate metrics
      if (tokenEl) tokenEl.textContent = totalTokens;
      if (tpsEl) tpsEl.textContent = systemTps > 0 ? `${systemTps} t/s` : '—';
      if (latencyEl) latencyEl.textContent = decodeLatency > 0 ? `${decodeLatency}s` : '—';
    }
  }, preset.interval);

  appState.ocrStreamTimer = streamTimer;
}

function sanitizeRenderedMarkdown(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  const blockedTags = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'FORM', 'INPUT', 'BUTTON', 'META', 'LINK']);

  div.querySelectorAll('*').forEach(element => {
    if (blockedTags.has(element.tagName)) {
      element.remove();
      return;
    }
    [...element.attributes].forEach(attribute => {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (name.startsWith('on') || name === 'srcdoc') {
        element.removeAttribute(attribute.name);
      }
      if ((name === 'href' || name === 'src') && /^(javascript|vbscript):/.test(value)) {
        element.removeAttribute(attribute.name);
      }
    });
  });
  return div.innerHTML;
}

function fallbackMarkdownParser(md) {
  if (!md) return '';
  const lines = md.split('\n');
  let html = '';
  let inTable = false;
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Image tag: ![Alt](url)
    const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imgMatch) {
      if (inTable) { html += '</tbody></table></div>'; inTable = false; }
      if (inList) { html += '</ul>'; inList = false; }
      html += `<div style="text-align:center;margin:16px 0;"><img src="${imgMatch[2]}" alt="${imgMatch[1]}" style="max-width:100%;height:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.12);" /></div>`;
      continue;
    }

    // Horizontal Rule
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      if (inTable) { html += '</tbody></table></div>'; inTable = false; }
      if (inList) { html += '</ul>'; inList = false; }
      html += '<hr style="border:0;border-top:1px solid rgba(255,255,255,0.12);margin:20px 0;" />';
      continue;
    }

    // Headings
    if (line.startsWith('### ')) {
      if (inTable) { html += '</tbody></table></div>'; inTable = false; }
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h3 style="color:#ffffff;margin:16px 0 8px;font-size:16px;font-weight:600;">${line.substring(4)}</h3>`;
      continue;
    }
    if (line.startsWith('## ')) {
      if (inTable) { html += '</tbody></table></div>'; inTable = false; }
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h2 style="color:#ffffff;margin:20px 0 10px;font-size:18px;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:6px;">${line.substring(3)}</h2>`;
      continue;
    }
    if (line.startsWith('# ')) {
      if (inTable) { html += '</tbody></table></div>'; inTable = false; }
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h1 style="color:#ffffff;margin:24px 0 12px;font-size:22px;font-weight:700;border-bottom:1px solid rgba(255,255,255,0.12);padding-bottom:8px;">${line.substring(2)}</h1>`;
      continue;
    }

    // Tables: | col1 | col2 |
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const cells = line.split('|').map(c => c.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      if (cells.every(c => /^[-: ]+$/.test(c))) {
        continue;
      }
      if (!inTable) {
        if (inList) { html += '</ul>'; inList = false; }
        html += '<div style="overflow-x:auto;margin:16px 0;"><table style="width:100%;border-collapse:collapse;font-size:13px;border:1px solid rgba(255,255,255,0.12);">';
        html += '<thead><tr style="background:rgba(255,255,255,0.06);">';
        cells.forEach(c => { html += `<th style="padding:8px 12px;border:1px solid rgba(255,255,255,0.1);color:#ffffff;text-align:left;font-weight:600;">${c}</th>`; });
        html += '</tr></thead><tbody>';
        inTable = true;
        continue;
      } else {
        html += `<tr style="background:${i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent'};">`;
        cells.forEach(c => { html += `<td style="padding:8px 12px;border:1px solid rgba(255,255,255,0.08);color:#d4d4d8;">${c}</td>`; });
        html += '</tr>';
        continue;
      }
    } else if (inTable) {
      html += '</tbody></table></div>';
      inTable = false;
    }

    // Lists: - item or * item
    if (/^[-*]\s+/.test(line.trim())) {
      if (!inList) { html += '<ul style="padding-left:20px;margin:8px 0;line-height:1.6;">'; inList = true; }
      html += `<li style="color:#d4d4d8;margin-bottom:4px;">${line.trim().replace(/^[-*]\s+/, '')}</li>`;
      continue;
    } else if (inList && line.trim() === '') {
      html += '</ul>';
      inList = false;
    }

    // Paragraphs / lines
    if (line.trim()) {
      let formatted = line
        .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<div style="text-align:center;margin:12px 0;"><img src="$2" alt="$1" style="max-width:100%;height:auto;border-radius:6px;border:1px solid rgba(255,255,255,0.12);" /></div>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#ffffff;">$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em style="color:#e4e4e7;">$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:4px;font-family:monospace;font-size:12px;">$1</code>');
      html += `<p style="margin-bottom:12px;line-height:1.65;color:#d4d4d8;">${formatted}</p>`;
    }
  }

  if (inTable) html += '</tbody></table></div>';
  if (inList) html += '</ul>';
  return html;
}

function updateVisualizationPanel(text) {
  const container = document.getElementById('visualizationContent');
  if (!container) return;

  if (appState.currentTab === 'json') {
    const ast = {
      model: 'HorizonOCR',
      mode: appState.activeDashMode,
      tokens: Math.floor((text || '').length / 3.5),
      nodes: [
        { type: 'header', level: 1, text: 'HorizonOCR Output' },
        { type: 'content', raw: (text || '').substring(0, 120) + '...' }
      ]
    };
    container.innerHTML = `<pre style="color:#a1a1aa;font-family:var(--font-mono);">${JSON.stringify(ast, null, 2)}</pre>`;
    return;
  }

  // Rendered view — progressive rich text streaming.
  if (text && text.trim()) {
    // 1. Transform custom image tags: ![Alt Text | filename.png] -> ![Alt Text](/api/images/filename.png)
    let renderableText = text.replace(/!\[([^\]]*?)\|\s*([^\]]+?\.(?:png|jpg|jpeg|webp|gif|svg))\s*\](?!\()/gi, (match, alt, imgFile) => {
      const cleanAlt = alt.trim() || 'Document Image';
      const cleanFile = imgFile.trim();
      return `![${cleanAlt}](${apiUrl('/api/images/' + encodeURIComponent(cleanFile))})`;
    });

    // 2. Transform bare image filename URLs: ![Alt Text](filename.png) -> ![Alt Text](/api/images/filename.png)
    renderableText = renderableText.replace(/!\[([^\]]*?)\]\((?!https?:\/\/|\/|data:)([^)\s]+?\.(?:png|jpg|jpeg|webp|gif|svg))\)/gi, (match, alt, imgFile) => {
      return `![${alt}](${apiUrl('/api/images/' + encodeURIComponent(imgFile.trim()))})`;
    });

    let renderedHtml = '';
    if (typeof marked !== 'undefined') {
      try {
        if (typeof marked.parse === 'function') {
          renderedHtml = marked.parse(renderableText);
        } else if (typeof marked === 'function') {
          renderedHtml = marked(renderableText);
        }
      } catch (e) {
        console.warn('[Marked.js parse error]', e);
      }
    }

    if (!renderedHtml) {
      renderedHtml = fallbackMarkdownParser(renderableText);
    }

    container.innerHTML = sanitizeRenderedMarkdown(renderedHtml);

    if (typeof renderMathInElement !== 'undefined') {
      try {
        renderMathInElement(container, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false},
            {left: '\\(', right: '\\)', display: false},
            {left: '\\[', right: '\\]', display: true}
          ],
          throwOnError: false
        });
      } catch (e) {
        console.warn('[KaTeX Error]', e);
      }
    }
  } else {
    container.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:40px 0;font-size:13px;">
      <p>Layout visualization will appear here.</p>
      <p style="margin-top:12px;font-size:11px;">Processing document structure...</p>
    </div>`;
  }
}

/**
 * Render a pixel-perfect document reconstruction on a white page canvas.
 */
function renderFaithfulDocumentPage(blocks, pageNum) {
  const container = document.getElementById('visualizationContent');
  if (!container) return;

  // Determine page aspect ratio from the Input Document image
  const docImg = document.getElementById('ocrDocumentImg');
  let aspectRatio = 1 / 1.4142; // A4 portrait default
  if (docImg && docImg.naturalWidth > 0 && docImg.naturalHeight > 0) {
    aspectRatio = docImg.naturalWidth / docImg.naturalHeight;
  }

  // Sort blocks by vertical position for correct stacking order
  const sortedBlocks = [...blocks].sort((a, b) => {
    const dy = (a.y || 0) - (b.y || 0);
    if (Math.abs(dy) > 0.5) return dy;
    return (a.x || 0) - (b.x || 0);
  });

  // Build the white page canvas
  let html = `<div class="viz-page-canvas" style="
    position:relative;
    width:100%;
    aspect-ratio:${aspectRatio.toFixed(4)};
    background:#ffffff;
    margin:0 auto;
    overflow:hidden;
    box-shadow:0 2px 20px rgba(0,0,0,0.35);
    border-radius:3px;
  ">`;

  // Render every block at its exact position
  sortedBlocks.forEach(block => {
    if (block.type === 'image' && (block.src || block.img_name)) {
      const src = block.src || apiUrl('/api/images/' + (block.img_name || ''));
      html += _renderReplicaImage({ ...block, src });
    } else if (block.type === 'table' && block.rows && block.rows.length > 0) {
      html += _renderReplicaTable(block);
    } else {
      html += _renderReplicaText(block);
    }
  });

  html += '</div>';

  // Page indicator
  html += `<div style="text-align:center;padding:8px 0 2px;font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">
    Page ${pageNum} of ${appState.totalPages || 1}
  </div>`;

  container.innerHTML = html;
}

/** Map common PDF font name fragments to CSS-safe font families */
function _mapPdfFont(pdfFontName) {
  if (!pdfFontName) return 'serif';
  const f = pdfFontName.toLowerCase();
  if (f.includes('arial') || f.includes('helvetic') || f.includes('sans'))
    return '"Helvetica Neue", Arial, sans-serif';
  if (f.includes('times') || f.includes('roman'))
    return '"Times New Roman", Times, serif';
  if (f.includes('courier') || f.includes('mono') || f.includes('consol'))
    return '"Courier New", Courier, monospace';
  if (f.includes('georgia'))
    return 'Georgia, serif';
  if (f.includes('calibri'))
    return 'Calibri, "Segoe UI", sans-serif';
  if (f.includes('cambria'))
    return 'Cambria, Georgia, serif';
  if (f.includes('verdana'))
    return 'Verdana, Geneva, sans-serif';
  if (f.includes('tahoma'))
    return 'Tahoma, Verdana, sans-serif';
  if (f.includes('palatino') || f.includes('book'))
    return '"Palatino Linotype", "Book Antiqua", serif';
  if (f.includes('symbol'))
    return 'Symbol, serif';
  // Generic fallback based on bold/serif heuristics in the name
  if (f.includes('serif'))
    return 'serif';
  return 'sans-serif';
}

/** Render an image block at its exact document position */
function _renderReplicaImage(block) {
  return `<div style="
    position:absolute;
    left:${block.x}%;
    top:${block.y}%;
    width:${block.w}%;
    height:${block.h}%;
    overflow:hidden;
  "><img src="${escapeHtml(block.src)}" style="
    width:100%;
    height:100%;
    object-fit:contain;
    display:block;
  " alt="Document image" /></div>`;
}

/** Render a table block as an HTML table at its exact document position */
function _renderReplicaTable(block) {
  const rows = block.rows;
  const nrows = rows.length;
  const ncols = block.ncols || (rows[0] ? rows[0].length : 1);
  
  // Calculate cell dimensions
  const cellHeight = nrows > 0 ? (100 / nrows) : 100;
  const cellWidth = ncols > 0 ? (100 / ncols) : 100;
  
  // Determine font size: scale proportionally to block height
  // A typical table in a PDF at 12pt over ~20% page height ≈ 0.6% per row
  const rowHeightPct = block.h / Math.max(nrows, 1);
  const fontSize = Math.max(7, Math.min(14, rowHeightPct * 4.5));

  let tableHtml = `<table style="
    width:100%;
    height:100%;
    border-collapse:collapse;
    table-layout:fixed;
    font-size:${fontSize}px;
    font-family:'Helvetica Neue',Arial,sans-serif;
    color:#111111;
    line-height:1.3;
  ">`;

  rows.forEach((row, rowIdx) => {
    const isHeader = rowIdx === 0;
    tableHtml += '<tr>';
    row.forEach(cell => {
      const tag = isHeader ? 'th' : 'td';
      const bgStyle = isHeader
        ? 'background:#f0f0f0;font-weight:600;'
        : (rowIdx % 2 === 0 ? 'background:#fafafa;' : 'background:#ffffff;');
      tableHtml += `<${tag} style="
        border:1px solid #cccccc;
        padding:2px 4px;
        text-align:left;
        vertical-align:middle;
        word-break:break-word;
        overflow:hidden;
        ${bgStyle}
      ">${escapeHtml(cell || '')}</${tag}>`;
    });
    tableHtml += '</tr>';
  });

  tableHtml += '</table>';

  return `<div style="
    position:absolute;
    left:${block.x}%;
    top:${block.y}%;
    width:${block.w}%;
    height:${block.h}%;
    overflow:hidden;
    box-sizing:border-box;
  ">${tableHtml}</div>`;
}

/** Render a text block at its exact document position with faithful typography */
function _renderReplicaText(block) {
  const text = block.text || '';
  
  // Font size: use the extracted point size, scaled relative to the canvas
  // The canvas uses aspect-ratio so we scale pts relative to a reference height.
  // At 150 DPI the PDF page height is ~1123px for A4; CSS pt ≈ 1.333px.
  const fontSizePt = block.fontSizePt || 12;
  // Use fontPct (font size as % of page height) to scale correctly within
  // the aspect-ratio canvas. Multiply by a factor that converts the percentage
  // to a visually correct CSS size within the container.
  const fontSizeCalc = block.fontPct
    ? `calc(${block.fontPct} * 0.72vh)`
    : `${fontSizePt}pt`;
  
  // Use a % based approach that works with aspect-ratio container
  // fontPct is fontSize/pageHeight * 100 — so fontPct% of the container height
  // is the correct rendered size.
  const fontSizeCss = block.fontPct
    ? `${(block.fontPct * 0.95).toFixed(2)}cqh`
    : `${fontSizePt * 1.333}px`;
  
  // Font family
  const fontFamily = _mapPdfFont(block.fontFamily || '');
  
  // Font weight & style
  const fontWeight = block.bold ? '700' : '400';
  const fontStyle = block.italic ? 'italic' : 'normal';
  
  // Text color
  const color = block.textColor || '#000000';
  
  // Alignment
  const textAlign = block.align || 'left';

  // Convert newlines to <br> for multi-line blocks
  const safeText = escapeHtml(text).replace(/\n/g, '<br>');
  
  // Heading blocks: slightly different styling
  let extraStyle = '';
  if (block.type === 'heading') {
    extraStyle = 'font-weight:700;';
  } else if (block.type === 'footer') {
    extraStyle = 'opacity:0.7;';
  }

  return `<div style="
    position:absolute;
    left:${block.x}%;
    top:${block.y}%;
    width:${block.w}%;
    height:${block.h}%;
    overflow:hidden;
    padding:0;
    margin:0;
    box-sizing:border-box;
    font-family:${fontFamily};
    font-size:${fontSizeCss};
    font-weight:${fontWeight};
    font-style:${fontStyle};
    color:${color};
    text-align:${textAlign};
    line-height:1.25;
    white-space:pre-wrap;
    word-break:break-word;
    ${extraStyle}
  ">${safeText}</div>`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function switchOutputTab(tab) {
  appState.currentTab = tab;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

  const tabRendered = document.getElementById('tabRendered');
  const tabJson = document.getElementById('tabJson');

  if (tab === 'rendered' && tabRendered) tabRendered.classList.add('active');
  if (tab === 'json' && tabJson) tabJson.classList.add('active');

  updateVisualizationPanel(appState.extractedText || "Processing...");
}

function copyOutputText() {
  navigator.clipboard.writeText(appState.extractedText).then(() => {
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
      copyBtn.innerHTML = `<i data-lucide="check" style="width:12px;height:12px;"></i> Copied!`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
      setTimeout(() => {
        copyBtn.innerHTML = `<i data-lucide="copy" style="width:12px;height:12px;"></i> Copy`;
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }, 2000);
    }
  });
}

function toggleExportDropdown() {
  const dropdown = document.getElementById('exportDropdown');
  if (!dropdown) return;

  const isOpen = dropdown.style.display !== 'none';
  dropdown.style.display = isOpen ? 'none' : 'block';

  if (!isOpen) {
    if (typeof lucide !== 'undefined') lucide.createIcons();
    setTimeout(() => {
      const closeHandler = (e) => {
        if (!dropdown.contains(e.target) && !e.target.closest('#exportBtn')) {
          dropdown.style.display = 'none';
          document.removeEventListener('click', closeHandler);
        }
      };
      document.addEventListener('click', closeHandler);
    }, 0);
  }
}

function exportMarkdownFile() {
  const blob = new Blob([appState.extractedText], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ocr_output_${Date.now()}.md`;
  a.click();
  URL.revokeObjectURL(url);

  const dropdown = document.getElementById('exportDropdown');
  if (dropdown) dropdown.style.display = 'none';
}

function exportTextFile() {
  const blob = new Blob([appState.extractedText], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ocr_output_${Date.now()}.text`;
  a.click();
  URL.revokeObjectURL(url);

  const dropdown = document.getElementById('exportDropdown');
  if (dropdown) dropdown.style.display = 'none';
}

function renderBoundingBoxesForPage(pageNum) {
  const container = document.getElementById('bboxContainer');
  if (!container) return;
  container.innerHTML = '';

  let boxes = appState.pageBboxes ? appState.pageBboxes[pageNum] : null;

  if (!boxes || boxes.length === 0) {
    // Try page 1 as fallback for single-page docs
    boxes = appState.pageBboxes ? appState.pageBboxes[1] || [] : [];
  }

  if (!boxes || boxes.length === 0) return;

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
