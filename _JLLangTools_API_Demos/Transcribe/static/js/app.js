// static/js/app.js

document.addEventListener('DOMContentLoaded', () => {
  const uploadBox       = document.getElementById('upload-box');
  const fileInput       = document.getElementById('file-input');
  const modelSelect     = document.getElementById('model-select');
  const progressCont    = document.getElementById('progress-container');
  const progressBar     = document.getElementById('upload-progress');
  const progressLabel   = document.getElementById('progress-label');
  const resetBtn        = document.getElementById('reset-page');

  let isYouTubeMode = false;

  // --- 1) Allow multiple file selection ---
  fileInput.multiple = true;

  // 2) Clicking the box opens file picker (unless you click on a form control)
  uploadBox.addEventListener('click', e => {
    // if the click was on an input, button, select, textarea or label, bail out
    if ( e.target.closest('input, button, select, textarea, label') ) {
      return;
    }
    // otherwise open the file picker
    fileInput.click();
  });
  

  // 3) Drag & drop handlers
  ['dragenter','dragover','dragleave','drop'].forEach(evt => {
    uploadBox.addEventListener(evt, e => e.preventDefault());
  });

  uploadBox.addEventListener('drop', e => {
    const dt = e.dataTransfer;
    const files = Array.from(dt.files);
    if (files.length > 0) {
      handleFiles(files);
    } else {
      // Attempt to read a dropped URL (e.g. dragging a link)
      const url = dt.getData('text/uri-list') || dt.getData('text/plain');
      if (url && /(youtube\.com|youtu\.be)/.test(url)) {
        handleYouTube(url.trim());
      }
    }
  });

  // 4) File‐picker change
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
      handleFiles(Array.from(fileInput.files));
    }
  });

  // 5) Main handler for one or more files
  function handleFiles(files) {
    isYouTubeMode = false;
    showProgressUI();

    // Build FormData with all selected files
    const form = new FormData();
    files.forEach(f => form.append('audio', f));
    form.append('lang_key', modelSelect.value);

    // Gather segments from your segment inputs
    const segments = Array.from(
      document.querySelectorAll('.segment-row')
    ).map(row => ({
      start: row.querySelector('input[name="start"]').value.trim(),
      end:   row.querySelector('input[name="end"]').value.trim()
    }));
    form.append('segments', JSON.stringify(segments));

    // Send via XHR so we can track upload progress
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/transcribe', true);

    xhr.upload.onprogress = e => {
      if (e.lengthComputable) {
        const pct = (e.loaded / e.total) * 100;
        progressBar.value = pct;
        progressLabel.textContent = `Uploading: ${Math.round(pct)}%`;
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        progressBar.value = 100;
        progressLabel.textContent = 'Upload complete — queued for processing';
      } else {
        progressLabel.textContent = `Error ${xhr.status}: ${xhr.statusText}`;
      }
      resetBtn.parentElement.classList.remove('hidden');
    };

    xhr.onerror = () => {
      progressLabel.textContent = 'Upload failed (network error)';
      resetBtn.parentElement.classList.remove('hidden');
    };

    xhr.send(form);
  }

  // 6) Handler for YouTube URLs
  function handleYouTube(url) {
    isYouTubeMode = true;
    showProgressUI();
    progressLabel.textContent = 'Enqueuing YouTube download…';

    const body = new URLSearchParams();
    body.append('youtube_url', url);
    body.append('lang_key', modelSelect.value);

    fetch('/transcribe', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body
    })
    .then(res => res.json())
    .then(json => {
      if (json.status === 'queued') {
        progressLabel.textContent = `Queued ${json.items.length} video(s)`;
      } else if (json.error) {
        progressLabel.textContent = `Error: ${json.error}`;
      }
      resetBtn.parentElement.classList.remove('hidden');
    })
    .catch(err => {
      progressLabel.textContent = `Network error`;
      resetBtn.parentElement.classList.remove('hidden');
    });
  }

  // 7) Show/hide UI elements, switch bar mode
  function showProgressUI() {
    uploadBox.classList.add('hidden');
    progressCont.classList.remove('hidden');

    // Reset the bar
    progressBar.value = 0;
    if (isYouTubeMode) {
      // Indeterminate
      progressBar.removeAttribute('max');
    } else {
      progressBar.max = 100;
    }
  }

  // 8) “Transcribe new file” button
  resetBtn.addEventListener('click', () => window.location.reload());
});
