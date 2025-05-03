document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('files-list');
  const viewer = document.getElementById('file-viewer');
  const downloadBtn = document.getElementById('download-btn');

  function clearSelection() {
    document.querySelectorAll('.file-row.selected').forEach(r => r.classList.remove('selected'));
    document.querySelectorAll('.file-children').forEach(c => c.remove());
    viewer.innerHTML = '';
    downloadBtn.disabled = true;
    downloadBtn.removeAttribute('data-path');
  }

  function createChildRow(label, path) {
    const r = document.createElement('div');
    r.className = 'file-row';
    r.textContent = label;
    r.dataset.path = path;
    return r;
  }

  list.addEventListener('click', e => {
    const top = e.target.closest('#files-list > .file-row');
    if (top) {
      if (top.classList.contains('selected')) {
        const next = top.nextElementSibling;
        if (next && next.classList.contains('file-children')) next.remove();
        return;
      }

      clearSelection();
      top.classList.add('selected');

      const folder = top.dataset.folder;
      const segCount = parseInt(top.dataset.segments, 10);
      const child = document.createElement('div');
      child.className = 'file-children';

      child.appendChild(createChildRow('Log file', `${folder}/${folder}.log`));
      child.appendChild(createChildRow('Request.json', `${folder}/request.json`));

      if (segCount === 1) {
        child.appendChild(createChildRow('Text file', `${folder}/segment_1/assembled_result/${folder}_1.txt`));
        child.appendChild(createChildRow('Subtitle file', `${folder}/segment_1/assembled_result/${folder}_1.srt`));
        child.appendChild(createChildRow('Mappings', `${folder}/segment_1/chunks_mapping.json`));
      } else {
        for (let i = 1; i <= segCount; i++) {
          const segRow = document.createElement('div');
          segRow.className = 'file-row';
          segRow.textContent = `Result ${i}`;
          segRow.dataset.seg = i;
          child.appendChild(segRow);
        }
      }

      top.after(child);
      return;
    }

    const childRow = e.target.closest('.file-children .file-row');
    if (childRow) {
      e.stopPropagation();
      const container = childRow.parentElement;
      container.querySelectorAll('.file-row.selected').forEach(r => r.classList.remove('selected'));
      childRow.classList.add('selected');

      if (childRow.dataset.seg) {
        const seg = childRow.dataset.seg;
        const parent = container.previousElementSibling;
        const folder = parent.dataset.folder;
        const next = childRow.nextElementSibling;
        if (next && next.classList.contains('file-children')) {
          next.remove();
          return;
        }
        const sub = document.createElement('div');
        sub.className = 'file-children';
        sub.appendChild(createChildRow('Text file', `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.txt`));
        sub.appendChild(createChildRow('Subtitle file', `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.srt`));
        sub.appendChild(createChildRow('Mappings', `${folder}/segment_${seg}/chunks_mapping.json`));
        childRow.after(sub);
      } else {
        viewer.innerHTML = '';
        downloadBtn.disabled = false;
        const path = childRow.dataset.path;
        downloadBtn.dataset.path = path;

        fetch(`/files/preview?path=${encodeURIComponent(path)}`)
          .then(r => r.text())
          .then(html => {
            viewer.innerHTML = html;
          })
          .catch(() => {
            viewer.textContent = '⚠️ Error loading file';
          });
      }
    }
  });

  downloadBtn.addEventListener('click', () => {
    const path = downloadBtn.dataset.path;
    if (!path) return;
    const a = document.createElement('a');
    a.href = `/download/${encodeURIComponent(path)}`;
    a.download = path.split('/').pop();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });
});
