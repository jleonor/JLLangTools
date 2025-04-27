document.addEventListener('DOMContentLoaded', () => {
  const box = document.getElementById('upload-box');
  const fileInput = document.getElementById('file-input');
  const form = document.getElementById('upload-form');
  const modelSelect = document.getElementById('model-select');
  const progCont = document.getElementById('progress-container');
  const progress = document.getElementById('upload-progress');
  const statusCont = document.getElementById('status-container');
  const resetPage = document.getElementById('reset-page');

  // load models
  fetch('/languages')
    .then(r => r.json())
    .then(data => {
      modelSelect.innerHTML = '';
      data.languages.forEach(lang => {
        const opt = document.createElement('option');
        opt.value = lang;
        opt.textContent = lang;
        modelSelect.appendChild(opt);
      });
    });

  // click or drop handling
  // only open file picker when we click *outside* any form controls
  box.addEventListener('click', e => {
    if (e.target.closest('#upload-form')) return;
    fileInput.click();
  });
  ['dragenter', 'dragover'].forEach(evt => {
    box.addEventListener(evt, e => e.preventDefault());
  });
  box.addEventListener('drop', e => {
    e.preventDefault();
    fileInput.files = e.dataTransfer.files;
    upload();
  });
  fileInput.addEventListener('change', upload);

  function upload() {
    const file = fileInput.files[0];
    if (!file) return;

    // collect all segments into an array of {start, end}
    const segments = Array.from(
      document.querySelectorAll('.segment-row')
    ).map(row => ({
      start: row.querySelector('input[name="start"]').value.trim(),
      end:   row.querySelector('input[name="end"]').value.trim()
    }));

    // capture “sent time” in ISO format
    const sentTime = new Date().toISOString();

    // build form data with JSON-encoded segments
    const data = new FormData();
    data.append('audio', file);
    data.append('lang_key', modelSelect.value);
    data.append('segments', JSON.stringify(segments));
    data.append('sent_time', sentTime);         // ← new field

    // show progress
    box.classList.add('hidden');
    progCont.classList.remove('hidden');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/transcribe');
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) {
        progress.value = (e.loaded / e.total) * 100;
      }
    };
    xhr.onload = () => {
      progCont.classList.add('hidden');
      statusCont.classList.remove('hidden');
    };
    xhr.send(data);
  }

  resetPage.addEventListener('click', () => window.location.reload());

  // segment controls
  document.getElementById('add-seg').onclick = () => {
    const container = document.getElementById('segments-container');
    const row = container.querySelector('.segment-row').cloneNode(true);
    container.appendChild(row);
  };
  document.getElementById('reset-seg').onclick = () => {
    const container = document.getElementById('segments-container');
    container.innerHTML = container.querySelector('.segment-row').outerHTML;
  };
});
