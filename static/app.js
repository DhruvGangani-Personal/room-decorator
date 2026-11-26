(() => {
  const form = document.getElementById('visualizer-form');
  const apiStatusEl = document.getElementById('api-status');
  const btnGenerate = document.getElementById('btn-generate');
  const btnSpinner = btnGenerate.querySelector('.btn-spinner');
  const btnLabel = btnGenerate.querySelector('.btn-label');
  const btnReset = document.getElementById('btn-reset');

  const viewTabs = document.getElementById('view-tabs');
  const toolbarActions = document.getElementById('toolbar-actions');
  const btnDownload = document.getElementById('btn-download');
  const canvasMeta = document.getElementById('canvas-meta');

  const errorBanner = document.getElementById('error-banner');
  const errorMessage = document.getElementById('error-message');
  const btnDismissError = document.getElementById('btn-dismiss-error');

  const stateEmpty = document.getElementById('state-empty');
  const stateLoading = document.getElementById('state-loading');
  const elapsedTimerEl = document.getElementById('elapsed-timer');

  const viewResult = document.getElementById('view-result');
  const viewCompare = document.getElementById('view-compare');
  const viewSideBySide = document.getElementById('view-side-by-side');

  const resultImg = document.getElementById('result-img');
  const compareBefore = document.getElementById('compare-before');
  const compareAfter = document.getElementById('compare-after');
  const compareBeforeWrap = document.getElementById('compare-before-wrap');
  const compareHandle = document.getElementById('compare-handle');
  const sbsBefore = document.getElementById('sbs-before');
  const sbsAfter = document.getElementById('sbs-after');

  const historyStrip = document.getElementById('history-strip');
  const historyItems = document.getElementById('history-items');

  let currentView = 'result';
  let mainPreviewUrl = null;
  let activeResultUrl = null;
  let timerInterval = null;
  const sessionHistory = [];

  // 1. Health Check
  async function checkHealth() {
    try {
      const res = await fetch('/health');
      if (!res.ok) throw new Error('API unhealthy');
      const data = await res.json();
      apiStatusEl.className = 'status-pill status-healthy';
      apiStatusEl.querySelector('.status-text').textContent = data.status === 'healthy' ? 'API Connected' : 'API Ready';
    } catch {
      apiStatusEl.className = 'status-pill status-error';
      apiStatusEl.querySelector('.status-text').textContent = 'API Offline';
    }
  }
  checkHealth();

  // 2. Dropzone & File Preview Handling
  document.querySelectorAll('.dropzone').forEach((zone) => {
    const inputId = zone.dataset.input;
    const input = document.getElementById(inputId);
    const emptyEl = zone.querySelector('.dropzone-empty');
    const previewEl = zone.querySelector('.dropzone-preview');
    const imgEl = previewEl.querySelector('img');
    const nameEl = previewEl.querySelector('.preview-name');
    const clearBtn = previewEl.querySelector('.btn-clear');

    function setFile(file) {
      if (!file) return;
      const url = URL.createObjectURL(file);
      if (imgEl.dataset.blobUrl) {
        URL.revokeObjectURL(imgEl.dataset.blobUrl);
      }
      imgEl.dataset.blobUrl = url;
      imgEl.src = url;
      nameEl.textContent = file.name;
      emptyEl.hidden = true;
      previewEl.hidden = false;

      if (inputId === 'main_image') {
        mainPreviewUrl = url;
      }

      // Auto-select "matt" finish if user uploads a tile swatch and finish is still "None"
      if (inputId === 'floor_tile_image') {
        autoSelectFinish('floor_finish');
        analyzeTileAndUpdateGrout('floor', imgEl);
      } else if (
        inputId === 'wall_tile_image_1' ||
        inputId === 'wall_tile_image_2' ||
        inputId === 'wall_tile_image_3'
      ) {
        autoSelectFinish('wall_finish');
        analyzeTileAndUpdateGrout('wall', imgEl);
      }
    }

    function clearFile(e) {
      if (e) e.stopPropagation();
      input.value = '';
      if (imgEl.dataset.blobUrl) {
        URL.revokeObjectURL(imgEl.dataset.blobUrl);
        delete imgEl.dataset.blobUrl;
      }
      imgEl.removeAttribute('src');
      nameEl.textContent = '';
      previewEl.hidden = true;
      emptyEl.hidden = false;
      if (inputId === 'main_image') {
        mainPreviewUrl = null;
      } else if (inputId === 'floor_tile_image') {
        resetTileTone('floor');
      } else if (
        inputId === 'wall_tile_image_1' ||
        inputId === 'wall_tile_image_2' ||
        inputId === 'wall_tile_image_3'
      ) {
        refreshWallTileTone();
      }
    }

    zone.addEventListener('click', () => input.click());
    clearBtn.addEventListener('click', clearFile);

    input.addEventListener('change', () => {
      if (input.files && input.files[0]) {
        setFile(input.files[0]);
      }
    });

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
      zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        const dt = new DataTransfer();
        dt.items.add(e.dataTransfer.files[0]);
        input.files = dt.files;
        setFile(e.dataTransfer.files[0]);
      }
    });
  });

  function autoSelectFinish(fieldName) {
    const hiddenInput = document.getElementById(fieldName);
    if (hiddenInput && !hiddenInput.value) {
      setSegmentedValue(fieldName, 'matt');
    }
  }

  // 3. Chip Groups (Scene & Tile Sizes)
  document.querySelectorAll('.chip-group').forEach((group) => {
    const targetId = group.dataset.target;
    const targetInput = document.getElementById(targetId);

    group.addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      group.querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      targetInput.value = chip.dataset.value;
      if (targetId === 'floor_size_lable') { updateSizeAnalysis('floor', targetInput.value); updateCalculator(); }
      if (targetId === 'wall_size_lable') { updateSizeAnalysis('wall', targetInput.value); updateCalculator(); }
    });

    targetInput.addEventListener('input', () => {
      const val = targetInput.value.trim().toLowerCase();
      group.querySelectorAll('.chip').forEach((c) => {
        c.classList.toggle('active', c.dataset.value.toLowerCase() === val);
      });
      if (targetId === 'floor_size_lable') { updateSizeAnalysis('floor', targetInput.value); updateCalculator(); }
      if (targetId === 'wall_size_lable') { updateSizeAnalysis('wall', targetInput.value); updateCalculator(); }
    });
  });

  // 3b. Live Tile Size & Aspect Ratio Analysis from tile_size_model.pkl
  let sizeAnalysisTimers = {};
  function updateSizeAnalysis(prefix, sizeVal) {
    const badge = document.getElementById(`${prefix}-size-analysis`);
    if (!badge) return;
    clearTimeout(sizeAnalysisTimers[prefix]);
    sizeAnalysisTimers[prefix] = setTimeout(async () => {
      try {
        const res = await fetch(`/api/analyze-tile-size?size=${encodeURIComponent(sizeVal)}`);
        if (!res.ok) return;
        const info = await res.json();
        if (!info.valid) {
          badge.textContent = 'Enter size in mm (e.g. 600x1200 mm)';
          return;
        }
        const modelText = info.matched_model
          ? `${info.exact_match ? 'Exact' : 'Closest'} .pkl: ${info.matched_model.filename}`
          : 'Custom size';
        badge.textContent = `Ratio ${info.aspect_ratio_label} • ~${info.tiles_per_meter_w}×${info.tiles_per_meter_h} tiles/m • ${modelText}`;
      } catch {
        badge.textContent = '';
      }
    }, 150);
  }
  updateSizeAnalysis('floor', document.getElementById('floor_size_lable').value);
  updateSizeAnalysis('wall', document.getElementById('wall_size_lable').value);

  // 4. Segmented Controls (Finishes)
  function setSegmentedValue(name, value) {
    const control = document.querySelector(`.segmented-control[data-name="${name}"]`);
    const hiddenInput = document.getElementById(name);
    if (!control || !hiddenInput) return;
    hiddenInput.value = value;
    control.querySelectorAll('.seg-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.value === value);
    });
  }

  document.querySelectorAll('.segmented-control').forEach((control) => {
    const name = control.dataset.name;
    control.addEventListener('click', (e) => {
      const btn = e.target.closest('.seg-btn');
      if (!btn) return;
      setSegmentedValue(name, btn.dataset.value);
    });
  });

  // 4b. Smart Grout Color Extraction & Picker
  const DEFAULT_GROUT_SWATCHES = [
    { name: 'Warm Ivory', hex: '#EFECE6' },
    { name: 'Soft Sand', hex: '#D8CFC2' },
    { name: 'Cool Silver', hex: '#B4B9C0' },
    { name: 'Charcoal', hex: '#3B3F45' }
  ];

  function rgbToHex(r, g, b) {
    return (
      '#' +
      [r, g, b]
        .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0'))
        .join('')
        .toUpperCase()
    );
  }

  function adjustColor(r, g, b, factor) {
    if (factor >= 0) {
      return rgbToHex(r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor);
    }
    const f = 1 + factor;
    return rgbToHex(r * f, g * f, b * f);
  }

  function extractDominantColor(imgEl) {
    return new Promise((resolve) => {
      const compute = () => {
        try {
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');
          canvas.width = 24;
          canvas.height = 24;
          ctx.drawImage(imgEl, 0, 0, 24, 24);
          const { data } = ctx.getImageData(0, 0, 24, 24);
          let r = 0, g = 0, b = 0, count = 0;
          for (let i = 0; i < data.length; i += 4) {
            if (data[i + 3] < 128) continue;
            r += data[i];
            g += data[i + 1];
            b += data[i + 2];
            count++;
          }
          if (!count) return resolve(null);
          resolve({ r: r / count, g: g / count, b: b / count });
        } catch {
          resolve(null);
        }
      };
      if (imgEl.complete && imgEl.naturalWidth > 0) {
        compute();
      } else {
        imgEl.addEventListener('load', compute, { once: true });
      }
    });
  }

  function buildRecommendedGroutSwatches(rgb) {
    if (!rgb) return DEFAULT_GROUT_SWATCHES;
    const { r, g, b } = rgb;
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    const isWarm = r >= b;

    if (luminance > 0.68) {
      // Light tile -> soft tone-on-tone + medium contrast + dark contrast
      return [
        { name: 'Tonal Light', hex: adjustColor(r, g, b, -0.14) },
        { name: isWarm ? 'Warm Sand' : 'Mist Gray', hex: isWarm ? '#D4C7B8' : '#C2C7CE' },
        { name: isWarm ? 'Taupe Stone' : 'Slate Gray', hex: isWarm ? '#8F7E6E' : '#7D848D' },
        { name: 'Deep Contrast', hex: '#3B3D42' }
      ];
    } else if (luminance < 0.35) {
      // Dark tile -> light ash, silver, warm stone, dark match
      return [
        { name: 'Light Ash', hex: '#D6D8DC' },
        { name: isWarm ? 'Warm Cream' : 'Silver Mist', hex: isWarm ? '#E4DCD0' : '#AEB4BC' },
        { name: 'Tonal Highlight', hex: adjustColor(r, g, b, 0.38) },
        { name: 'Deep Slate', hex: '#2B2E33' }
      ];
    }
    // Mid-tone / wood / brown / terracotta tile
    return [
      { name: isWarm ? 'Warm Almond' : 'Soft Pearl', hex: adjustColor(r, g, b, 0.55) },
      { name: 'Tonal Match', hex: adjustColor(r, g, b, -0.25) },
      { name: isWarm ? 'Espresso' : 'Graphite', hex: adjustColor(r, g, b, -0.58) },
      { name: 'Crisp Off-White', hex: '#EFECE6' }
    ];
  }

  function setGroutSelection(prefix, value, labelText, activeType, activeEl, fromSync = false) {
    const picker = document.getElementById(`${prefix}-grout-picker`);
    const hidden = document.getElementById(`${prefix}_grout_color`);
    const labelEl = document.getElementById(`${prefix}-grout-label`);
    const autoBtn = picker.querySelector('.grout-auto-btn');
    const customBtn = picker.querySelector('.grout-custom-btn');

    hidden.value = value;
    labelEl.textContent = labelText;

    autoBtn.classList.toggle('active', activeType === 'auto');
    customBtn.classList.toggle('active', activeType === 'custom');
    picker.querySelectorAll('.grout-swatch').forEach((s) => {
      s.classList.toggle('active', activeType === 'swatch' && s === activeEl);
    });

    const syncToggle = document.getElementById('sync_grout');
    if (!fromSync && syncToggle && syncToggle.checked) {
      const otherPrefix = prefix === 'floor' ? 'wall' : 'floor';
      const syncLabel = value ? `${labelText} (Synced)` : 'Auto (Synced wall & floor)';
      labelEl.textContent = syncLabel;
      setGroutSelection(otherPrefix, value, syncLabel, activeType === 'swatch' ? 'custom' : activeType, null, true);
      if (value) {
        const otherDot = document.getElementById(`${otherPrefix}-custom-dot`);
        const hexMatch = value.match(/#[0-9A-Fa-f]{6}/);
        if (otherDot && hexMatch) otherDot.style.background = hexMatch[0];
      }
    }
  }

  function renderGroutSwatches(prefix, swatches) {
    const container = document.getElementById(`${prefix}-grout-swatches`);
    container.innerHTML = '';
    swatches.forEach((sw) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'grout-swatch';
      btn.style.backgroundColor = sw.hex;
      btn.title = `${sw.name} (${sw.hex})`;
      btn.dataset.value = `${sw.name} (${sw.hex})`;
      btn.addEventListener('click', () => {
        setGroutSelection(prefix, btn.dataset.value, `${sw.name} (${sw.hex})`, 'swatch', btn);
      });
      container.appendChild(btn);
    });
  }

  async function analyzeTileAndUpdateGrout(prefix, imgEl) {
    const rgb = await extractDominantColor(imgEl);
    const indicator = document.getElementById(`${prefix}-tone-indicator`);
    const dot = document.getElementById(`${prefix}-tone-dot`);
    if (rgb) {
      dot.style.backgroundColor = rgbToHex(rgb.r, rgb.g, rgb.b);
      indicator.hidden = false;
    }
    renderGroutSwatches(prefix, buildRecommendedGroutSwatches(rgb));
  }

  function resetTileTone(prefix) {
    document.getElementById(`${prefix}-tone-indicator`).hidden = true;
    renderGroutSwatches(prefix, DEFAULT_GROUT_SWATCHES);
  }

  function refreshWallTileTone() {
    const wallIds = ['wall_tile_image_1', 'wall_tile_image_3', 'wall_tile_image_2'];
    for (const id of wallIds) {
      const input = document.getElementById(id);
      if (input.files && input.files[0]) {
        const img = input.closest('.dropzone').querySelector('.dropzone-preview img');
        analyzeTileAndUpdateGrout('wall', img);
        return;
      }
    }
    resetTileTone('wall');
  }

  ['floor', 'wall'].forEach((prefix) => {
    renderGroutSwatches(prefix, DEFAULT_GROUT_SWATCHES);
    const picker = document.getElementById(`${prefix}-grout-picker`);
    const autoBtn = picker.querySelector('.grout-auto-btn');
    const nativeColor = document.getElementById(`${prefix}-grout-native`);
    const customDot = document.getElementById(`${prefix}-custom-dot`);

    autoBtn.addEventListener('click', () => {
      setGroutSelection(prefix, '', 'Auto (contrasting grout)', 'auto');
    });

    nativeColor.addEventListener('input', () => {
      const hex = nativeColor.value.toUpperCase();
      customDot.style.background = hex;
      setGroutSelection(prefix, hex, `Custom (${hex})`, 'custom');
    });
  });

  const syncGroutCheckbox = document.getElementById('sync_grout');
  if (syncGroutCheckbox) {
    syncGroutCheckbox.addEventListener('change', () => {
      if (syncGroutCheckbox.checked) {
        const floorVal = document.getElementById('floor_grout_color').value;
        const wallVal = document.getElementById('wall_grout_color').value;
        const chosen = floorVal || wallVal;
        const label = chosen ? `${chosen} (Synced)` : 'Auto (Synced wall & floor)';
        setGroutSelection('floor', chosen, label, chosen ? 'custom' : 'auto', null, true);
        setGroutSelection('wall', chosen, label, chosen ? 'custom' : 'auto', null, true);
      } else {
        ['floor', 'wall'].forEach((prefix) => {
          const val = document.getElementById(`${prefix}_grout_color`).value;
          const labelEl = document.getElementById(`${prefix}-grout-label`);
          if (labelEl) {
            labelEl.textContent = val || 'Auto (contrasting grout)';
          }
        });
      }
    });
  }

  // 5. View Switcher
  function setView(view) {
    currentView = view;
    viewTabs.querySelectorAll('.view-tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.view === view);
    });

    viewResult.hidden = view !== 'result';
    viewCompare.hidden = view !== 'compare';
    viewSideBySide.hidden = view !== 'side-by-side';
  }

  viewTabs.addEventListener('click', (e) => {
    const tab = e.target.closest('.view-tab');
    if (!tab) return;
    setView(tab.dataset.view);
  });

  // 6. Before / After Slider
  let isDraggingSlider = false;

  function updateSlider(clientX) {
    const rect = viewCompare.getBoundingClientRect();
    if (!rect.width) return;
    const pct = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100));
    compareBeforeWrap.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
    compareHandle.style.left = `${pct}%`;
    compareHandle.setAttribute('aria-valuenow', Math.round(pct));
  }

  compareHandle.addEventListener('pointerdown', (e) => {
    isDraggingSlider = true;
    compareHandle.setPointerCapture(e.pointerId);
    updateSlider(e.clientX);
  });

  viewCompare.addEventListener('pointerdown', (e) => {
    isDraggingSlider = true;
    updateSlider(e.clientX);
  });

  window.addEventListener('pointermove', (e) => {
    if (!isDraggingSlider) return;
    updateSlider(e.clientX);
  });

  window.addEventListener('pointerup', () => {
    isDraggingSlider = false;
  });

  // 7. Error Banner
  function showError(msg) {
    errorMessage.textContent = msg;
    errorBanner.hidden = false;
  }

  function hideError() {
    errorBanner.hidden = true;
    errorMessage.textContent = '';
  }

  btnDismissError.addEventListener('click', hideError);

  // 8. Display Render Result
  function showRender(resultUrl, beforeUrl, metaText) {
    activeResultUrl = resultUrl;
    resultImg.src = resultUrl;
    compareAfter.src = resultUrl;
    sbsAfter.src = resultUrl;

    if (beforeUrl) {
      compareBefore.src = beforeUrl;
      sbsBefore.src = beforeUrl;
    }

    btnDownload.href = resultUrl;
    btnDownload.download = `atelier_tile_${Date.now()}.png`;

    stateEmpty.hidden = true;
    stateLoading.hidden = true;
    viewTabs.hidden = false;
    toolbarActions.hidden = false;
    canvasMeta.textContent = metaText;
    setView(currentView);
  }

  function addHistoryItem(resultUrl, beforeUrl, scene) {
    const item = {
      id: Date.now(),
      resultUrl,
      beforeUrl,
      scene,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    sessionHistory.unshift(item);
    renderHistory();
  }

  function renderHistory() {
    if (sessionHistory.length === 0) {
      historyStrip.hidden = true;
      return;
    }
    historyStrip.hidden = false;
    historyItems.innerHTML = '';

    sessionHistory.forEach((item) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `history-thumb ${item.resultUrl === activeResultUrl ? 'active' : ''}`;
      btn.title = `${item.scene} (${item.time})`;
      const img = document.createElement('img');
      img.src = item.resultUrl;
      img.alt = item.scene;
      btn.appendChild(img);
      btn.addEventListener('click', () => {
        showRender(item.resultUrl, item.beforeUrl, `${item.scene} • ${item.time}`);
        renderHistory();
      });
      historyItems.appendChild(btn);
    });
  }

  // 9. Form Submission
  function setLoading(loading) {
    btnGenerate.disabled = loading;
    btnSpinner.hidden = !loading;
    btnLabel.textContent = loading ? 'Generating…' : 'Generate Render';

    if (loading) {
      stateEmpty.hidden = true;
      viewResult.hidden = true;
      viewCompare.hidden = true;
      viewSideBySide.hidden = true;
      stateLoading.hidden = false;
      const start = performance.now();
      elapsedTimerEl.textContent = '0.0s';
      timerInterval = setInterval(() => {
        const secs = ((performance.now() - start) / 1000).toFixed(1);
        elapsedTimerEl.textContent = `${secs}s`;
      }, 100);
    } else {
      stateLoading.hidden = true;
      if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
      }
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();

    const mainInput = document.getElementById('main_image');
    if (!mainInput.files || !mainInput.files[0]) {
      showError('Please upload a Room Reference image first.');
      return;
    }

    const formData = new FormData();
    formData.append('main_image', mainInput.files[0]);

    const optionalFiles = [
      'floor_tile_image',
      'wall_tile_image_1',
      'wall_tile_image_2',
      'wall_tile_image_3'
    ];
    optionalFiles.forEach((id) => {
      const el = document.getElementById(id);
      if (el.files && el.files[0]) {
        formData.append(id, el.files[0]);
      }
    });

    const sceneVal = document.getElementById('scene').value.trim() || 'living room';
    formData.append('scene', sceneVal);
    formData.append('floor_size_lable', document.getElementById('floor_size_lable').value.trim() || '600x1200 mm');
    formData.append('wall_size_lable', document.getElementById('wall_size_lable').value.trim() || '600x1200 mm');

    const floorFinish = document.getElementById('floor_finish').value;
    if (floorFinish) formData.append('floor_finish', floorFinish);

    const wallFinish = document.getElementById('wall_finish').value;
    if (wallFinish) formData.append('wall_finish', wallFinish);

    formData.append('floor_orientation', document.getElementById('floor_orientation').value || 'horizontal');
    formData.append('wall_orientation', document.getElementById('wall_orientation').value || 'horizontal');
    formData.append('floor_pattern', document.getElementById('floor_pattern').value || 'grid');
    formData.append('wall_pattern', document.getElementById('wall_pattern').value || 'grid');
    formData.append('floor_grout_width', document.getElementById('floor_grout_width').value || '2 mm');
    formData.append('wall_grout_width', document.getElementById('wall_grout_width').value || '2 mm');
    formData.append('aspect_ratio', document.getElementById('aspect_ratio').value || '4:3');

    const floorGroutColor = document.getElementById('floor_grout_color').value;
    if (floorGroutColor) formData.append('floor_grout_color', floorGroutColor);

    const wallGroutColor = document.getElementById('wall_grout_color').value;
    if (wallGroutColor) formData.append('wall_grout_color', wallGroutColor);

    const syncGrout = document.getElementById('sync_grout');
    if (syncGrout && syncGrout.checked) {
      formData.append('sync_grout', 'true');
    }

    const beforeSnapshotUrl = mainPreviewUrl;
    setLoading(true);
    canvasMeta.textContent = `Rendering ${sceneVal}…`;

    try {
      const response = await fetch('/generate-prompt', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        let errText = `Server error (${response.status})`;
        try {
          const errJson = await response.json();
          errText = errJson.message || errJson.error || errText;
        } catch {
          // fallback to status text
        }
        throw new Error(errText);
      }

      const blob = await response.blob();
      const resultUrl = URL.createObjectURL(blob);
      const elapsed = elapsedTimerEl.textContent;
      const metaText = `${sceneVal} • Rendered in ${elapsed}`;

      setLoading(false);
      showRender(resultUrl, beforeSnapshotUrl, metaText);
      addHistoryItem(resultUrl, beforeSnapshotUrl, sceneVal);
    } catch (err) {
      setLoading(false);
      if (activeResultUrl) {
        setView(currentView);
      } else {
        stateEmpty.hidden = false;
      }
      canvasMeta.textContent = 'Generation failed';
      showError(err.message || 'An unexpected error occurred.');
    }
  });

  // 10. Reset Form
  btnReset.addEventListener('click', () => {
    hideError();
    document.querySelectorAll('.btn-clear').forEach((btn) => btn.click());
    document.getElementById('scene').value = 'living room';
    document.getElementById('floor_size_lable').value = '600x1200 mm';
    document.getElementById('wall_size_lable').value = '600x1200 mm';
    document.querySelectorAll('.chip-group').forEach((group) => {
      const targetVal = document.getElementById(group.dataset.target).value;
      group.querySelectorAll('.chip').forEach((c) => {
        c.classList.toggle('active', c.dataset.value === targetVal);
      });
    });
    setSegmentedValue('floor_finish', '');
    setSegmentedValue('wall_finish', '');
    setSegmentedValue('floor_orientation', 'horizontal');
    setSegmentedValue('wall_orientation', 'horizontal');
    setSegmentedValue('floor_pattern', 'grid');
    setSegmentedValue('wall_pattern', 'grid');
    setSegmentedValue('floor_grout_width', '2 mm');
    setSegmentedValue('wall_grout_width', '2 mm');
    setSegmentedValue('aspect_ratio', '4:3');
    setGroutSelection('floor', '', 'Auto (contrasting grout)', 'auto', null, true);
    setGroutSelection('wall', '', 'Auto (contrasting grout)', 'auto', null, true);
    const syncGrout = document.getElementById('sync_grout');
    if (syncGrout) syncGrout.checked = false;
    resetTileTone('floor');
    resetTileTone('wall');
    updateCalculator();
  });

  // 11. Tile Area & Box Calculator
  let calcUnit = 'ft';
  const calcSurface = document.getElementById('calc-surface');
  const calcLen = document.getElementById('calc-len');
  const calcWid = document.getElementById('calc-wid');
  const calcBox = document.getElementById('calc-box');
  const calcResults = document.getElementById('calc-results');

  function parseMmPair(str) {
    const m = (str || '').match(/(\d+)\s*[xX×]\s*(\d+)/);
    return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : [600, 1200];
  }

  function updateCalculator() {
    if (!calcResults) return;
    const len = parseFloat(calcLen.value) || 0;
    const wid = parseFloat(calcWid.value) || 0;
    const perBox = Math.max(1, parseInt(calcBox.value, 10) || 1);
    const areaSqM = calcUnit === 'ft' ? len * wid * 0.092903 : len * wid;
    const sizeStr =
      calcSurface.value === 'wall'
        ? document.getElementById('wall_size_lable').value
        : document.getElementById('floor_size_lable').value;
    const [wMm, hMm] = parseMmPair(sizeStr);
    const tileAreaSqM = (wMm / 1000) * (hMm / 1000);
    const exactTiles = tileAreaSqM > 0 ? Math.ceil(areaSqM / tileAreaSqM) : 0;
    const withWastage = Math.ceil(exactTiles * 1.1);
    const boxes = Math.ceil(withWastage / perBox);

    calcResults.innerHTML = `
      <div class="calc-stat"><strong>${areaSqM.toFixed(1)} m²</strong><span>Area</span></div>
      <div class="calc-stat"><strong>${withWastage}</strong><span>Tiles (+10%)</span></div>
      <div class="calc-stat"><strong>${boxes}</strong><span>Boxes</span></div>
    `;
  }

  document.querySelectorAll('.calc-unit').forEach((btn) => {
    btn.addEventListener('click', () => {
      calcUnit = btn.dataset.unit;
      document.querySelectorAll('.calc-unit').forEach((b) => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.unit-lbl').forEach((el) => (el.textContent = calcUnit));
      updateCalculator();
    });
  });

  [calcSurface, calcLen, calcWid, calcBox].forEach((el) => {
    if (el) el.addEventListener('input', updateCalculator);
  });
  ['floor_size_lable', 'wall_size_lable'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updateCalculator);
  });
  updateCalculator();
})();
