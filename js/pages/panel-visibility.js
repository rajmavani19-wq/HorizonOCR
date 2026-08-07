/*
  ================================================================
  HorizonOCR - Panel Visibility Controller
  Manages hide/show of OCR and Visualisation panels in the 
  3-panel workspace without affecting processing workflow.
  ================================================================
*/

// Track which panels are currently hidden
const hiddenPanels = new Set();

// Panel metadata for display names and Lucide icon names
const PANEL_META = {
  ocr: { name: 'OCR', icon: 'terminal', panelId: 'panelOcr' },
  visualization: { name: 'Visualisation', icon: 'layout-grid', panelId: 'panelVisualization' }
};

/**
 * Toggle the 3-dot context menu on a panel header.
 * Closes any other open panel menus first.
 */
function togglePanelMenu(panelKey) {
  // Close all menus first
  document.querySelectorAll('.panel-menu-dropdown').forEach(menu => {
    if (menu.id !== `panelMenu${capitalize(panelKey)}`) {
      menu.style.display = 'none';
    }
  });

  const menuId = `panelMenu${capitalize(panelKey)}`;
  const menu = document.getElementById(menuId);
  if (!menu) return;

  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';

  // Close when clicking outside
  if (menu.style.display === 'block') {
    setTimeout(() => {
      const closeHandler = (e) => {
        if (!menu.contains(e.target) && !e.target.closest('.panel-menu-btn')) {
          menu.style.display = 'none';
          document.removeEventListener('click', closeHandler);
        }
      };
      document.addEventListener('click', closeHandler);
    }, 0);
  }
}

/**
 * Hide a panel and update the grid layout dynamically.
 */
function hidePanel(panelKey) {
  const meta = PANEL_META[panelKey];
  if (!meta) return;

  hiddenPanels.add(panelKey);

  // Hide the panel DOM element
  const panelEl = document.getElementById(meta.panelId);
  if (panelEl) panelEl.classList.add('panel-hidden');

  // Update the grid CSS classes
  updateGridLayout();

  // Close the 3-dot menu
  const menuId = `panelMenu${capitalize(panelKey)}`;
  const menu = document.getElementById(menuId);
  if (menu) menu.style.display = 'none';

  // Refresh the Hide Screen dropdown content
  renderHiddenScreensList();

  // Re-initialize Lucide icons for any new DOM
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Show a previously hidden panel and restore the grid layout.
 */
function showPanel(panelKey) {
  const meta = PANEL_META[panelKey];
  if (!meta) return;

  hiddenPanels.delete(panelKey);

  // Show the panel DOM element
  const panelEl = document.getElementById(meta.panelId);
  if (panelEl) panelEl.classList.remove('panel-hidden');

  // Update the grid CSS classes
  updateGridLayout();

  // Refresh the Hide Screen dropdown content
  renderHiddenScreensList();

  // Re-initialize Lucide icons
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Update the grid container CSS classes to dynamically resize columns.
 * Document panel stays fixed at 32%. Remaining panels fill available space.
 */
function updateGridLayout() {
  const grid = document.getElementById('ocrPanelGrid');
  if (!grid) return;

  grid.classList.remove('hide-ocr', 'hide-visualization');

  if (hiddenPanels.has('ocr')) grid.classList.add('hide-ocr');
  if (hiddenPanels.has('visualization')) grid.classList.add('hide-visualization');
}

/**
 * Toggle the "Hide Screen" dropdown in the toolbar.
 */
function toggleHideScreenDropdown() {
  const dropdown = document.getElementById('hideScreenDropdown');
  if (!dropdown) return;

  const isOpen = dropdown.style.display !== 'none';
  dropdown.style.display = isOpen ? 'none' : 'block';

  // Close when clicking outside
  if (!isOpen) {
    renderHiddenScreensList();
    setTimeout(() => {
      const closeHandler = (e) => {
        if (!dropdown.contains(e.target) && !e.target.closest('#hideScreenBtn')) {
          dropdown.style.display = 'none';
          document.removeEventListener('click', closeHandler);
        }
      };
      document.addEventListener('click', closeHandler);
    }, 0);
  }
}

/**
 * Render the list of currently hidden screens inside the dropdown.
 * Each hidden screen shows its name and a red "Remove" button.
 */
function renderHiddenScreensList() {
  const listEl = document.getElementById('hiddenScreensList');
  if (!listEl) return;

  if (hiddenPanels.size === 0) {
    listEl.innerHTML = '<div class="hidden-empty-state">No screens are hidden</div>';
    return;
  }

  let html = '';
  hiddenPanels.forEach(panelKey => {
    const meta = PANEL_META[panelKey];
    if (!meta) return;
    html += `
      <div class="hidden-screen-item">
        <div class="hidden-screen-name">
          <i data-lucide="${meta.icon}" style="width:14px;height:14px;"></i>
          ${meta.name}
        </div>
        <div class="hidden-screen-remove" onclick="showPanel('${panelKey}')">
          <i data-lucide="x" style="width:11px;height:11px;"></i> Remove
        </div>
      </div>
    `;
  });

  listEl.innerHTML = html;

  // Re-initialize Lucide icons for the newly injected HTML
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Capitalize a string's first letter (for ID construction).
 */
function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
