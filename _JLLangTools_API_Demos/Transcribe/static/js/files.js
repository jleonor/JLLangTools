// static/js/files.js
// Handles the two-level expandable file tree and file viewing

document.addEventListener('DOMContentLoaded', () => {
    const list = document.getElementById('files-list');
    const viewer = document.getElementById('file-viewer');
    const downloadBtn = document.getElementById('download-btn');
  
    // Clear any selection and remove all child lists
    function clearSelection() {
      // Remove 'selected' class from all rows
      document.querySelectorAll('.file-row.selected').forEach(r => r.classList.remove('selected'));
      // Remove all expanded child containers
      document.querySelectorAll('.file-children').forEach(c => c.remove());
      // Reset viewer and download button
      viewer.textContent = '';
      downloadBtn.disabled = true;
      downloadBtn.removeAttribute('data-path');
    }
  
    // Remove only selection state (used for segment toggles)
    function clearRowSelection() {
      document.querySelectorAll('.file-row.selected').forEach(r => r.classList.remove('selected'));
    }
  
    // Create a row representing a file (leaf node)
    function createChildRow(label, path) {
      const r = document.createElement('div');
      r.className = 'file-row';
      r.textContent = label;
      r.dataset.path = path;
      return r;
    }
  
    // Fetch and display file content
    function showFile(path) {
      fetch(`/files/content?path=${encodeURIComponent(path)}`)
        .then(r => r.text())
        .then(txt => {
          viewer.textContent = txt;
          downloadBtn.disabled = false;
          downloadBtn.setAttribute('data-path', path);
        });
    }
  
    // Delegate all clicks within the file list
    list.addEventListener('click', e => {
      // Top-level row click (batch)
      const top = e.target.closest('#files-list > .file-row');
      if (top) {
        clearSelection();
        top.classList.add('selected');
  
        const folder = top.dataset.folder;
        const filename = top.dataset.filename;
        const segCount = parseInt(top.dataset.segments, 10);
  
        // Build the child container
        const child = document.createElement('div');
        child.className = 'file-children';
  
        // Always include log and request.json
        child.appendChild(createChildRow('Log file', `${folder}/${folder}.log`));
        child.appendChild(createChildRow('Request.json', `${folder}/request.json`));
  
        if (segCount === 1) {
          // Single segment: assembler names files using the folder name
          child.appendChild(createChildRow(
            'Text file (viewing)',
            `${folder}/segment_1/assembled_result/${folder}_1.txt`
          ));
          child.appendChild(createChildRow(
            'Subtitle file (raw)',
            `${folder}/segment_1/assembled_result/${folder}_1.srt`
          ));
          child.appendChild(createChildRow(
            'Mappings',
            `${folder}/segment_1/chunks_mapping.json`
          ));
        } else if (segCount > 1) {
          // Multiple segments: list as "Result 1…N"
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
  
      // Second-level click: either one of the created child rows or a segment entry
      const childRow = e.target.closest('.file-children .file-row');
      if (childRow) {
        e.stopPropagation();
  
        // If it's a segment entry
        if (childRow.dataset.seg) {
          // Only clear prior selections, keep the segment list in place
          clearRowSelection();
          childRow.classList.add('selected');
  
          // Remove any existing sub-children under this segment
          const next = childRow.nextElementSibling;
          if (next && next.classList.contains('file-children')) {
            next.remove();
            return;
          }
  
          const seg = childRow.dataset.seg;
          const parent = childRow.closest('.file-children').previousElementSibling;
          const folder = parent.dataset.folder;
          const filename = parent.dataset.filename;

          const sub = document.createElement('div');
          sub.className = 'file-children';
          // Assembler names these files using folder name + segment index
          sub.appendChild(createChildRow(
            'Text file (viewing)',
            `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.txt`
          ));
          sub.appendChild(createChildRow(
            'Subtitle file (raw)',
            `${folder}/segment_${seg}/assembled_result/${folder}_${seg}.srt`
          ));
          sub.appendChild(createChildRow(
            'Mappings',
            `${folder}/segment_${seg}/chunks_mapping.json`
          ));
          childRow.after(sub);
        } else {
          // Leaf file clicked
          clearRowSelection();
          childRow.classList.add('selected');
          showFile(childRow.dataset.path);
        }
      }
    });
  
    // Download button handler
    downloadBtn.addEventListener('click', () => {
      const path = downloadBtn.getAttribute('data-path');
      if (path) window.location = `/download/${encodeURIComponent(path)}`;
    });
});
