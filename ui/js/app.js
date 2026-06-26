// API client
const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.json();
  },
  async put(path, body) {
    const res = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.json();
  },
  async delete(path) {
    const res = await fetch(path, { method: 'DELETE' });
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.json();
  },
};

// UI state
let state = {
  activeView: 'record',
  recordingId: null,
  liveTranscriptInterval: null,
  copilotPollInterval: null,
};

// View management
document.querySelectorAll('.nav-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const view = btn.dataset.view;
    switchView(view);
  });
});

function switchView(view) {
  // Set display directly: the inline style="display:none" on sections has
  // higher specificity than the .view.active CSS rule, so toggling the class
  // alone wouldn't reveal Library/Settings.
  document.querySelectorAll('.view').forEach((v) => {
    v.classList.remove('active');
    v.style.display = 'none';
  });
  const target = document.getElementById(view);
  target.classList.add('active');
  target.style.display = 'block';

  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.remove('active'));
  document.querySelector(`[data-view="${view}"]`).classList.add('active');

  state.activeView = view;

  if (view === 'library') loadMeetings();
  if (view === 'settings') loadSettings();
}

// Modal
function showModal(title, content) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = content;
  document.getElementById('modal').style.display = 'flex';
}

function hideModal() {
  document.getElementById('modal').style.display = 'none';
}

document.querySelector('.modal-close').addEventListener('click', hideModal);
document.getElementById('modal').addEventListener('click', (e) => {
  if (e.target === document.getElementById('modal')) hideModal();
});

// ============================================================
// RECORD VIEW
// ============================================================

document.getElementById('record-start-btn').addEventListener('click', async () => {
  const title = document.getElementById('record-title').value.trim() || 'Meeting';
  try {
    const res = await api.post('/api/record/start', { title });
    state.recordingId = res.id;

    document.getElementById('record-start-btn').style.display = 'none';
    document.getElementById('record-stop-btn').style.display = 'block';
    document.getElementById('record-status').style.display = 'block';

    // Poll live transcript every 2s
    state.liveTranscriptInterval = setInterval(updateLiveTranscript, 2000);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

async function updateLiveTranscript() {
  try {
    const res = await api.get('/api/record/live');
    document.getElementById('live-transcript').textContent = res.transcript || '(waiting for audio...)';
  } catch {
    // ignore
  }
}

document.getElementById('record-stop-btn').addEventListener('click', async () => {
  clearInterval(state.liveTranscriptInterval);
  try {
    const res = await api.post('/api/record/stop', {});
    document.getElementById('record-start-btn').style.display = 'block';
    document.getElementById('record-stop-btn').style.display = 'none';
    document.getElementById('record-status').style.display = 'none';
    document.getElementById('live-transcript').textContent = '';
    state.recordingId = null;

    alert(`Meeting recorded: ${res.id}\nDuration: ${res.duration_secs}s`);
    switchView('library');
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

// ============================================================
// LIBRARY VIEW
// ============================================================

async function loadMeetings() {
  try {
    const res = await api.get('/api/meetings');
    const list = document.getElementById('meetings-list');
    if (!res.meetings || res.meetings.length === 0) {
      list.innerHTML = '<p class="text-muted">No meetings yet.</p>';
      return;
    }

    list.innerHTML = res.meetings.map((m) => {
      const duration = m.duration_secs ? `${Math.round(m.duration_secs / 60)}m` : '—';
      const date = new Date(m.started_at * 1000).toLocaleString();
      const badgeClass = m.status === 'done' ? 'badge' : 'badge' + (m.status === 'recording' ? '' : '');
      return `
        <div class="meeting-item">
          <h3>${m.title}</h3>
          <p>${date}</p>
          <p>${duration} • ${m.transcript_quality || 'pending'}</p>
          <span class="badge">${m.status}</span>
          <div class="actions">
            ${m.status === 'recorded' ? `<button class="btn btn-secondary" onclick="showTranscribeOptions('${m.id}')">Re-transcribe</button>` : ''}
            ${m.transcript_quality ? `<button class="btn btn-secondary" onclick="generateNotes('${m.id}')">Notes</button>` : ''}
            ${m.status === 'done' ? `<button class="btn btn-secondary" onclick="exportMeeting('${m.id}', 'md')">MD</button><button class="btn btn-secondary" onclick="exportMeeting('${m.id}', 'pdf')">PDF</button>` : ''}
            <button class="btn btn-danger" onclick="deleteMeeting('${m.id}')">Delete</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    document.getElementById('meetings-list').innerHTML = `<p class="text-error">Error: ${err.message}</p>`;
  }
}

function showTranscribeOptions(meetingId) {
  let html = '<div class="form-group"><label>Choose Whisper model:</label><select id="transcribe-model">';
  // Will populate with available models from /api/stt/models
  api.get('/api/stt/models').then((res) => {
    html = '<div class="form-group"><label>Choose Whisper model:</label><select id="transcribe-model">';
    res.models.forEach((m) => {
      html += `<option value="${m}">${m}</option>`;
    });
    html += '</select></div><button class="btn btn-primary" onclick="doTranscribe(\'' + meetingId + '\')">Transcribe</button>';
    showModal('Re-transcribe Meeting', html);
  }).catch((err) => {
    showModal('Re-transcribe Meeting', `<p class="text-error">Error: ${err.message}</p>`);
  });
}

async function doTranscribe(meetingId) {
  const model = document.getElementById('transcribe-model')?.value || '';
  const url = model ? `/api/meetings/${meetingId}/transcribe?model=${model}` : `/api/meetings/${meetingId}/transcribe`;
  try {
    const res = await api.post(url, {});
    hideModal();
    alert(`Transcribed with ${res.model}\n\n${res.transcript.substring(0, 200)}...`);
    loadMeetings();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

async function generateNotes(meetingId) {
  try {
    const res = await api.post(`/api/meetings/${meetingId}/notes`, { include_transcript: true });
    let html = `
      <h3>Summary</h3>
      <p>${res.notes.summary}</p>
      <h3>Decisions</h3>
      <ul>
        ${res.notes.decisions.map((d) => `<li>${d}</li>`).join('')}
      </ul>
      <h3>Action Items</h3>
      <ul>
        ${res.notes.action_items.map((a) => `<li><strong>${a.task}</strong> (${a.owner || 'unassigned'})</li>`).join('')}
      </ul>
    `;
    showModal('Meeting Notes', html);
    loadMeetings();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

async function exportMeeting(meetingId, fmt) {
  try {
    const res = await api.post(`/api/meetings/${meetingId}/export?fmt=${fmt}`, {});
    alert(`Exported to:\n${res.path}`);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

async function deleteMeeting(meetingId) {
  if (!confirm('Delete this meeting?')) return;
  try {
    await api.delete(`/api/meetings/${meetingId}`);
    loadMeetings();
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

// ============================================================
// SETTINGS VIEW
// ============================================================

async function loadSettings() {
  // Load config
  try {
    const cfg = await api.get('/api/config');
    document.getElementById('llm-provider').value = cfg.llm.provider;
    document.getElementById('llm-model').value = cfg.llm.model;
    document.getElementById('copilot-ghe-host').value = cfg.llm.copilot_ghe_host || '';
    document.getElementById('openai-base-url').value = cfg.llm.base_url || '';

    // Show/hide provider sections
    updateLlmProviderUI();

    // Load STT models
    const stt = await api.get('/api/stt/models');
    const rtSel = document.getElementById('stt-realtime');
    const ofSel = document.getElementById('stt-offline');
    rtSel.innerHTML = stt.models.map((m) => `<option value="${m}">${m}</option>`).join('');
    ofSel.innerHTML = stt.models.map((m) => `<option value="${m}">${m}</option>`).join('');
    rtSel.value = stt.realtime;
    ofSel.value = stt.offline;
  } catch (err) {
    console.error('Error loading settings:', err);
  }
}

document.getElementById('llm-provider').addEventListener('change', updateLlmProviderUI);

function updateLlmProviderUI() {
  const provider = document.getElementById('llm-provider').value;
  document.getElementById('copilot-section').style.display = provider === 'copilot' ? 'block' : 'none';
  document.getElementById('ghe-section').style.display = provider === 'copilot' ? 'block' : 'none';
  document.getElementById('openai-section').style.display = provider === 'openai_compat' ? 'block' : 'none';
}

document.getElementById('llm-save-btn').addEventListener('click', async () => {
  const provider = document.getElementById('llm-provider').value;
  const model = document.getElementById('llm-model').value;
  const patch = {
    llm: {
      provider,
      model,
      copilot_ghe_host: document.getElementById('copilot-ghe-host').value || '',
      base_url: document.getElementById('openai-base-url').value || '',
    },
  };
  try {
    await api.put('/api/config', { patch });
    alert('LLM config saved.');
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

document.getElementById('stt-save-btn').addEventListener('click', async () => {
  const patch = {
    stt: {
      realtime_model: document.getElementById('stt-realtime').value,
      offline_model: document.getElementById('stt-offline').value,
    },
  };
  try {
    await api.put('/api/config', { patch });
    alert('STT config saved.');
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

// Copilot device-flow login
document.getElementById('copilot-login-start-btn').addEventListener('click', async () => {
  try {
    const res = await api.post('/api/copilot/login/start', {});
    document.getElementById('copilot-uri').textContent = res.verification_uri;
    document.getElementById('copilot-code').textContent = res.user_code;
    document.getElementById('copilot-code-section').style.display = 'block';
    document.getElementById('copilot-login-start-btn').style.display = 'none';

    // Auto-poll every interval seconds
    const interval = res.interval || 5;
    const expiresIn = res.expires_in || 900;
    const deadline = Date.now() + expiresIn * 1000;
    state.copilotPollInterval = setInterval(async () => {
      if (Date.now() > deadline) {
        clearInterval(state.copilotPollInterval);
        document.getElementById('copilot-status').innerHTML = '<span class="text-error">Device flow expired.</span>';
        return;
      }
      try {
        const pollRes = await api.post('/api/copilot/login/poll', {});
        if (pollRes.status === 'ok') {
          clearInterval(state.copilotPollInterval);
          document.getElementById('copilot-status').innerHTML = '<span class="text-success">✓ Authenticated!</span>';
          document.getElementById('copilot-code-section').style.display = 'none';
          document.getElementById('copilot-login-start-btn').style.display = 'block';
        } else if (pollRes.status === 'pending') {
          document.getElementById('copilot-status').innerHTML = '<span class="text-muted">Waiting for authorization...</span>';
        } else {
          clearInterval(state.copilotPollInterval);
          document.getElementById('copilot-status').innerHTML = `<span class="text-error">Error: ${pollRes.error}</span>`;
        }
      } catch (err) {
        document.getElementById('copilot-status').innerHTML = `<span class="text-error">Poll error: ${err.message}</span>`;
      }
    }, interval * 1000);

    // First poll immediately
    const pollRes = await api.post('/api/copilot/login/poll', {});
    if (pollRes.status === 'ok') {
      clearInterval(state.copilotPollInterval);
      document.getElementById('copilot-status').innerHTML = '<span class="text-success">✓ Authenticated!</span>';
      document.getElementById('copilot-code-section').style.display = 'none';
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

document.getElementById('copilot-login-poll-btn').addEventListener('click', async () => {
  try {
    const pollRes = await api.post('/api/copilot/login/poll', {});
    if (pollRes.status === 'ok') {
      clearInterval(state.copilotPollInterval);
      document.getElementById('copilot-status').innerHTML = '<span class="text-success">✓ Authenticated!</span>';
      document.getElementById('copilot-code-section').style.display = 'none';
      document.getElementById('copilot-login-start-btn').style.display = 'block';
    } else {
      document.getElementById('copilot-status').innerHTML = '<span class="text-muted">Still waiting...</span>';
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
});

// Initialize
window.addEventListener('load', () => {
  switchView('record');
});
