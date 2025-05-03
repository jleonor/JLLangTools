document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const modelSelect = document.getElementById('model-select');
  const progCont = document.getElementById('progress-container');
  const progress = document.getElementById('upload-progress');
  const statusCont = document.getElementById('status-container');
  const resetPage = document.getElementById('reset-page');
  const progressLabel = document.getElementById('progress-label');

  const uploadBox = document.getElementById('upload-box');
  const form = document.getElementById('upload-form');

  uploadBox.addEventListener('click', e => {
    if (e.target.closest('#upload-form')) return;
    fileInput.click();
  });

  ['dragenter', 'dragover'].forEach(evt => {
    uploadBox.addEventListener(evt, e => e.preventDefault());
  });
  uploadBox.addEventListener('drop', e => {
    e.preventDefault();
    fileInput.files = e.dataTransfer.files;
    upload();
  });
  fileInput.addEventListener('change', upload);

  function upload() {
    const file = fileInput.files[0];
    if (!file) return;

    const segments = Array.from(document.querySelectorAll('.segment-row')).map(row => ({
      start: row.querySelector('input[name="start"]').value.trim(),
      end: row.querySelector('input[name="end"]').value.trim()
    }));

    const sentTime = new Date().toISOString();
    const data = new FormData();
    data.append('audio', file);
    data.append('lang_key', modelSelect.value);
    data.append('segments', JSON.stringify(segments));
    data.append('sent_time', sentTime);

    uploadBox.classList.add('hidden');
    progCont.classList.remove('hidden');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/transcribe');
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) {
        const percent = (e.loaded / e.total) * 100;
        progress.value = percent;
        progressLabel.textContent = `Uploading: ${percent.toFixed(1)}%`;
      }
    };

    xhr.onload = () => {
      progCont.classList.add('hidden');
      statusCont.classList.remove('hidden');
    };
    xhr.send(data);
  }

  resetPage.addEventListener('click', () => window.location.reload());

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