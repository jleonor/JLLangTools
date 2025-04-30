// static/js/files.js

document.addEventListener('DOMContentLoaded', () => {
  const list        = document.getElementById('files-list');
  const viewer      = document.getElementById('file-viewer');
  const downloadBtn = document.getElementById('download-btn');

  // ——— renderRequestDetails: show request.json metadata ———
  function renderRequestDetails(data) {
    // clear viewer
    viewer.innerHTML = '';

    // 1) Show top-level fields in a list
    const ul = document.createElement('ul');
    ul.className = 'batch-meta';
    [
      ['Audio Filename', data.audio_filename],
      ['Language',       data.lang_key],
      ['Sent Time',      new Date(data.sent_time).toLocaleString()]
    ].forEach(([label, value]) => {
      const li = document.createElement('li');
      li.textContent = `${label}: ${value}`;
      ul.appendChild(li);
    });
    viewer.appendChild(ul);

    // 2) Show tasks in a table with status emojis
    const displayNames = {
      converterCompleted:   'Conversion',
      chunkerCompleted:     'Chunking',
      transcriberCompleted: 'Transcription',
      assemblerCompleted:   'Assembling',
      cleanerCompleted:     'Cleaning'
    };

    const table = document.createElement('table');
    table.className = 'batch-table';
    const header = table.insertRow();
    ['Task', 'Status', 'Timestamp'].forEach(h => {
      const th = document.createElement('th');
      th.textContent = h;
      header.appendChild(th);
    });

    Object.entries(data.tasks || {}).forEach(([task, ts]) => {
      const row = table.insertRow();
      // human-readable name
      const name = displayNames[task] || task;
      const status = ts ? '✅' : '⌛';
      // formatted timestamp or 'Pending'
      const tsDisplay = ts ? new Date(ts).toLocaleString() : 'Pending';
      row.insertCell().textContent = name;
      row.insertCell().textContent = status;
      row.insertCell().textContent = tsDisplay;
    });
    viewer.appendChild(table);
  }
  
  // 1) Clear any selection and remove all child lists
  function clearSelection() {
    document.querySelectorAll('.file-row.selected').forEach(r => r.classList.remove('selected'));
    document.querySelectorAll('.file-children').forEach(c => c.remove());
    viewer.innerHTML = '';
    downloadBtn.disabled = true;
    downloadBtn.removeAttribute('data-path');
  }

  // 2) Create a row representing a file (leaf node)
  function createChildRow(label, path) {
    const r = document.createElement('div');
    r.className = 'file-row';
    r.textContent = label;
    r.dataset.path = path;
    return r;
  }

  // 3) Helper: format milliseconds as HH:MM:SS
  function msToHms(ms) {
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    const pad = n => String(n).padStart(2, '0');
    return `${pad(h)}:${pad(m)}:${pad(s)}`;
  }

  // 4) Handlers for different file types
  const fileHandlers = {
    'chunks_mapping.json': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.json())
          .then(chunks => {
            const textMapPath = path.replace('chunks_mapping.json', 'text_mapping.json');
            return fetch(`/files/content?path=${encodeURIComponent(textMapPath)}`)
                    .then(r => r.json()).catch(() => [])
                    .then(texts => [chunks, texts]);
          })
          .then(([chunks, texts]) => {
            const normTexts = texts.map(t => ({
              audio_file: t.audio_file.replace(/\\/g, '/'),
              text_file:  t.text_file.replace(/\\/g, '/')
            }));

            const table = document.createElement('table');
            table.className = 'mapping-table';
            const header = table.insertRow();
            ['Start', 'End', 'Audio File', 'Text File'].forEach(h => {
              const th = document.createElement('th');
              th.textContent = h;
              header.appendChild(th);
            });

            chunks.forEach(entry => {
              const row = table.insertRow();
              row.insertCell().textContent = msToHms(entry.start_ms);
              row.insertCell().textContent = msToHms(entry.end_ms);
              row.insertCell().textContent = entry.chunk_file;
              const match = normTexts.find(t => t.audio_file === entry.chunk_file);
              row.insertCell().textContent = match ? match.text_file : '—';
            });

            viewer.appendChild(table);
          })
          .catch(err => {
            viewer.textContent = '⚠️ Error loading mapping';
            console.error(err);
          });
      },
      download(path) {
        const sibling = path.replace('chunks_mapping.json', 'text_mapping.json');
        [path, sibling].forEach(p => {
          const a = document.createElement('a');
          a.href = `/download/${encodeURIComponent(p)}`;
          a.download = p.split('/').pop();
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        });
      }
    },

    'text_mapping.json': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.json())
          .then(mapping => {
            const table = document.createElement('table');
            table.className = 'mapping-table';
            const header = table.insertRow();
            ['Audio File', 'Text File'].forEach(h => {
              const th = document.createElement('th');
              th.textContent = h;
              header.appendChild(th);
            });

            mapping.forEach(entry => {
              const row = table.insertRow();
              row.insertCell().textContent = entry.audio_file.replace(/\\/g, '/');
              row.insertCell().textContent = entry.text_file.replace(/\\/g, '/');
            });

            viewer.appendChild(table);
          })
          .catch(() => {
            viewer.textContent = '⚠️ Invalid JSON';
          });
      },
      download(path) {
        const a = document.createElement('a');
        a.href = `/download/${encodeURIComponent(path)}`;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    },

    'srt': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.text())
          .then(txt => {
            const entries = txt.trim().split(/\r?\n\r?\n/);
            const table = document.createElement('table');
            table.className = 'mapping-table';
            const header = table.insertRow();
            ['#', 'Start', 'End', 'Text'].forEach(h => {
              const th = document.createElement('th');
              th.textContent = h;
              header.appendChild(th);
            });

            entries.forEach(block => {
              const lines = block.split(/\r?\n/);
              if (lines.length >= 2) {
                const idx   = lines[0].trim();
                const times = lines[1].split('-->');
                const start = times[0].split(',')[0].trim();
                const end   = times[1].split(',')[0].trim();
                const text  = lines.slice(2).join(' ').trim();
                const row   = table.insertRow();
                [idx, start, end, text].forEach(val => {
                  const cell = row.insertCell();
                  cell.textContent = val;
                });
              }
            });

            viewer.appendChild(table);
          })
          .catch(err => {
            viewer.textContent = '⚠️ Error loading SRT';
            console.error(err);
          });
      },
      download(path) {
        const a = document.createElement('a');
        a.href = `/download/${encodeURIComponent(path)}`;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    },

    'request.json': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.json())
          .then(data => renderRequestDetails(data))
          .catch(err => {
            viewer.textContent = '⚠️ Error loading request metadata';
            console.error(err);
          });
      },
      download(path) {
        const a = document.createElement('a');
        a.href = `/download/${encodeURIComponent(path)}`;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    },

    'log': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.text())
          .then(txt => {
            const lines = txt.trim().split(/\r?\n/);
            const table = document.createElement('table');
            table.className = 'mapping-table';
            const hdr = table.insertRow();
            ['Date','Time','Level','Message'].forEach(h => {
              const th = document.createElement('th');
              th.textContent = h;
              hdr.appendChild(th);
            });
            const re = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (\w+): (.+)$/;
            lines.forEach(line => {
              const m = line.match(re);
              const row = table.insertRow();
              if (m) {
                row.insertCell().textContent = m[1];
                row.insertCell().textContent = m[2];
                row.insertCell().textContent = m[3];
                row.insertCell().textContent = m[4];
              } else {
                row.insertCell().textContent = '';
                row.insertCell().textContent = '';
                row.insertCell().textContent = '';
                row.insertCell().textContent = line;
              }
            });
            viewer.appendChild(table);
          })
          .catch(err => {
            viewer.textContent = '⚠️ Error loading log';
            console.error(err);
          });
      },
      download(path) {
        const a = document.createElement('a');
        a.href = `/download/${encodeURIComponent(path)}`;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    },

    'default': {
      view(path) {
        fetch(`/files/content?path=${encodeURIComponent(path)}`)
          .then(r => r.text())
          .then(txt => {
            viewer.textContent = txt;
          });
      },
      download(path) {
        const a = document.createElement('a');
        a.href = `/download/${encodeURIComponent(path)}`;
        a.download = path.split('/').pop();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    }
  };

  // Helper to choose handler key based on file extension or name
  function handlerKey(path) {
    if (path.toLowerCase().endsWith('.log'))       return 'log';
    if (path.endsWith('request.json'))             return 'request.json';
    if (path.endsWith('chunks_mapping.json'))      return 'chunks_mapping.json';
    if (path.endsWith('text_mapping.json'))        return 'text_mapping.json';
    if (path.toLowerCase().endsWith('.srt'))       return 'srt';
    return 'default';
  }

  // Updated click handler for sticky selection & toggle
  list.addEventListener('click', e => {
    const top = e.target.closest('#files-list > .file-row');
    if (top) {
      // toggle collapse if already selected
      if (top.classList.contains('selected')) {
        const next = top.nextElementSibling;
        if (next && next.classList.contains('file-children')) {
          next.remove();
        }
        return;
      }
      // select new folder and expand
      clearSelection();
      top.classList.add('selected');

      const folder   = top.dataset.folder;
      const segCount = parseInt(top.dataset.segments, 10);
      const child    = document.createElement('div');
      child.className = 'file-children';

      child.appendChild(createChildRow('Log file', `${folder}/${folder}.log`));
      child.appendChild(createChildRow('Request.json', `${folder}/request.json`));

      if (segCount === 1) {
        child.appendChild(createChildRow('Text file',      `${folder}/segment_1/assembled_result/${folder}_1.txt`));
        child.appendChild(createChildRow('Subtitle file',  `${folder}/segment_1/assembled_result/${folder}_1.srt`));
        child.appendChild(createChildRow('Mappings',      `${folder}/segment_1/chunks_mapping.json`));
      } else if (segCount > 1) {
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
        // toggle sub-children for segment entries
        const seg    = childRow.dataset.seg;
        const parent = container.previousElementSibling;
        const folder = parent.dataset.folder;
        const next   = childRow.nextElementSibling;
        if (next && next.classList.contains('file-children')) {
          next.remove();
          return;
        }
        const sub = document.createElement('div');
        sub.className = 'file-children';
        sub.appendChild(createChildRow('Text file (viewing)', `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.txt`));
        sub.appendChild(createChildRow('Subtitle file (raw)',  `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.srt`));
        sub.appendChild(createChildRow('Mappings',          `${folder}/segment_${seg}/chunks_mapping.json`));
        childRow.after(sub);
      } else {
        // leaf file: view/download
        viewer.innerHTML = '';
        downloadBtn.disabled = false;
        const path = childRow.dataset.path;
        downloadBtn.dataset.path = path;
        const key = handlerKey(path);
        fileHandlers[key].view(path);
      }
    }
  });

  // Download button handler
  downloadBtn.addEventListener('click', () => {
    const path = downloadBtn.dataset.path;
    if (!path) return;
    const key = handlerKey(path);
    fileHandlers[key].download(path);
  });
});