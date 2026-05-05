// Load config on page load
document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    loadVoiceLibrary();
    fetch('/api/version').then(r => r.json()).then(v => {
        const el = document.getElementById('app-version');
        if (el) el.textContent = `v${v.version}`;
    }).catch(() => {});
});

let currentConfig = {};
let voiceDb = { active_voice_id: '', voices: [] };

async function loadConfig() {
    try {
        const resp = await fetch('/api/config');
        const data = await resp.json();
        currentConfig = data;

        // Fill form fields
        document.getElementById('anthropicKey').value = data.anthropic_api_key || '';
        document.getElementById('elevenlabsKey').value = data.elevenlabs_api_key || '';
        document.getElementById('userName').value = data.user_name || '';
        document.getElementById('userAddress').value = data.user_address || '';
        document.getElementById('city').value = data.city || '';
        document.getElementById('timezone').value = data.timezone || 'Europe/Berlin';
        document.getElementById('lat').value = data.lat || '';
        document.getElementById('lon').value = data.lon || '';
        document.getElementById('kachelmannKey').value = data.kachelmann_api_key || '';
        document.getElementById('workspacePath').value = data.workspace_path || '';
        document.getElementById('obsidianPath').value = data.obsidian_inbox_path || '';
        document.getElementById('haUrl').value = data.ha_url || '';
        document.getElementById('haToken').value = data.ha_token || '';
        document.getElementById('browserUrl').value = data.browser_url || '';
        document.getElementById('spotifyTrack').value = data.spotify_track || '';

        // Toggle HA
        if (data.ha_enabled) {
            document.getElementById('haToggle').classList.add('on');
            document.getElementById('haFields').style.opacity = '1';
            document.getElementById('haFields').style.pointerEvents = 'auto';
        }

        // Toggle wake greeting
        if (data.wake_greeting_enabled !== false) {
            document.getElementById('wakeGreetingToggle').classList.add('on');
        }

        // Load available apps and populate dropdowns
        await loadAvailableApps();

        // Load selected programs
        loadPrograms(data.programs || []);

    } catch (e) {
        console.error('Config load failed:', e);
    }
}

// ── Voice Library ─────────────────────────────────────────────────────────

async function loadVoiceLibrary() {
    try {
        const resp = await fetch('/api/voices');
        voiceDb = await resp.json();
        renderActiveVoice();
    } catch(e) {
        const d = document.getElementById('activeVoiceDisplay');
        if (d) d.textContent = 'Fehler beim Laden';
    }
}

function renderActiveVoice() {
    const display = document.getElementById('activeVoiceDisplay');
    if (!display) return;
    const active = voiceDb.voices?.find(v => v.voice_id === voiceDb.active_voice_id);
    display.textContent = active ? `● ${active.name}` : (voiceDb.active_voice_id || '—');
}

function renderVoiceList() {
    const list = document.getElementById('voiceList');
    if (!list) return;
    if (!voiceDb.voices?.length) {
        list.innerHTML = '<div style="color:#555;font-size:0.85rem;text-align:center;padding:16px;">Noch keine Stimmen gespeichert.</div>';
        return;
    }
    list.innerHTML = voiceDb.voices.map((v, i) => {
        const isActive = v.voice_id === voiceDb.active_voice_id;
        return `<div style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:6px;background:${isActive ? 'rgba(76,191,126,0.08)' : 'rgba(42,158,226,0.04)'};border:1px solid ${isActive ? 'rgba(76,191,126,0.3)' : 'rgba(42,158,226,0.1)'};">
            <div style="flex:1;min-width:0;">
                <div style="font-size:0.85rem;font-weight:500;${isActive ? 'color:#4cbf7e' : ''}">${isActive ? '● ' : '○ '}${v.name}</div>
                <div style="font-size:0.7rem;color:#555;font-family:monospace;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${v.voice_id}</div>
            </div>
            <button class="field-row-action eye-btn" onclick="playVoicePreview('${v.voice_id}')" title="Testen">▶</button>
            ${isActive
                ? `<button class="field-row-action" style="border-color:#4cbf7e;color:#4cbf7e;cursor:default;opacity:0.6;" disabled>Aktiv</button>`
                : `<button class="field-row-action" onclick="activateVoice('${v.voice_id}')">Aktivieren</button>`}
            <button class="field-row-action eye-btn" onclick="removeVoice(${i})" title="Löschen" style="color:#e05252;">✗</button>
        </div>`;
    }).join('');
}

function openVoiceModal() {
    renderVoiceList();
    document.getElementById('voiceModal').classList.add('show');
}

function closeVoiceModal() {
    document.getElementById('voiceModal').classList.remove('show');
    document.getElementById('newVoiceName').value = '';
    document.getElementById('newVoiceId').value   = '';
}

async function activateVoice(voiceId) {
    try {
        const resp = await fetch('/api/voices/activate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({voice_id: voiceId})
        });
        const data = await resp.json();
        if (data.success) {
            voiceDb.active_voice_id = voiceId;
            renderActiveVoice();
            renderVoiceList();
            showToast('Stimme aktiviert', 'success');
        } else {
            showToast('Fehler: ' + (data.error || ''), 'error');
        }
    } catch(e) {
        showToast('Fehler: ' + e.message, 'error');
    }
}

async function addVoice() {
    const name    = document.getElementById('newVoiceName').value.trim();
    const voiceId = document.getElementById('newVoiceId').value.trim();
    if (!name || !voiceId) { showToast('Name und Voice ID erforderlich', 'error'); return; }
    if (voiceDb.voices.some(v => v.voice_id === voiceId)) { showToast('Voice ID bereits vorhanden', 'error'); return; }
    voiceDb.voices.push({name, voice_id: voiceId});
    await saveVoiceDb();
    document.getElementById('newVoiceName').value = '';
    document.getElementById('newVoiceId').value   = '';
    renderVoiceList();
    showToast(`"${name}" hinzugefügt`, 'success');
}

async function removeVoice(index) {
    if (voiceDb.voices[index]?.voice_id === voiceDb.active_voice_id) {
        showToast('Aktive Stimme kann nicht gelöscht werden', 'error');
        return;
    }
    voiceDb.voices.splice(index, 1);
    await saveVoiceDb();
    renderVoiceList();
    showToast('Stimme entfernt', 'success');
}

async function saveVoiceDb() {
    await fetch('/api/voices/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(voiceDb)
    });
}

async function playVoicePreview(voiceId) {
    try {
        const resp = await fetch('/api/preview_voice', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({voice_id: voiceId})
        });
        const data = await resp.json();
        if (data.audio) {
            new Audio('data:audio/mpeg;base64,' + data.audio).play();
        } else {
            showToast('Vorschau fehlgeschlagen: ' + (data.error || 'Kein Audio'), 'error');
        }
    } catch(e) {
        showToast('Vorschau fehlgeschlagen', 'error');
    }
}

async function previewActiveVoice() {
    if (!voiceDb.active_voice_id) { showToast('Keine aktive Stimme', 'error'); return; }
    await playVoicePreview(voiceDb.active_voice_id);
}

async function testNewVoice() {
    const voiceId = document.getElementById('newVoiceId').value.trim();
    if (!voiceId) { showToast('Voice ID eingeben', 'error'); return; }
    const btn = document.getElementById('testNewVoiceBtn');
    btn.textContent = '…'; btn.disabled = true;
    await playVoicePreview(voiceId);
    btn.textContent = '▶ Testen'; btn.disabled = false;
}

async function loadVoices(apiKey) {
    const key = apiKey || document.getElementById('elevenlabsKey')?.value.trim() || '';
    try {
        const url = key ? `/api/elevenlabs_voices?key=${encodeURIComponent(key)}` : '/api/elevenlabs_voices';
        return await (await fetch(url)).json();
    } catch(e) { return {voices: [], error: e.message}; }
}

async function testKey(type) {
    const btn = document.getElementById(type + 'Btn');
    const input = document.getElementById(type + 'Key');
    const key = input.value.trim();

    if (!key) {
        showToast('Kein API Key eingegeben', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = '…';

    try {
        const resp = await fetch('/api/test_key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type, key})
        });

        const data = await resp.json();
        if (data.success) {
            btn.classList.add('ok');
            btn.textContent = '✓ OK';
            showToast(type + ' API Key funktioniert', 'success');
            setTimeout(() => {
                btn.classList.remove('ok');
                btn.textContent = 'Testen';
            }, 3000);
        } else {
            btn.classList.add('err');
            btn.textContent = '✗ Fehler';
            showToast('API Key ungültig: ' + (data.error || 'Unbekannter Fehler'), 'error');
            setTimeout(() => {
                btn.classList.remove('err');
                btn.textContent = 'Testen';
            }, 3000);
        }
    } catch (e) {
        btn.classList.add('err');
        btn.textContent = '✗ Fehler';
        showToast('Test fehlgeschlagen: ' + e.message, 'error');
        setTimeout(() => {
            btn.classList.remove('err');
            btn.textContent = 'Testen';
        }, 3000);
    } finally {
        btn.disabled = false;
    }
}

function toggleHA() {
    const toggle = document.getElementById('haToggle');
    const fields = document.getElementById('haFields');
    toggle.classList.toggle('on');

    if (toggle.classList.contains('on')) {
        fields.style.opacity = '1';
        fields.style.pointerEvents = 'auto';
    } else {
        fields.style.opacity = '0.3';
        fields.style.pointerEvents = 'none';
    }
}

function toggleWakeGreeting() {
    const toggle = document.getElementById('wakeGreetingToggle');
    toggle.classList.toggle('on');
}

async function loadAvailableApps() {
    try {
        const resp = await fetch('/api/apps');
        const data = await resp.json();
        const apps = data.apps || [];

        // Populate all 6 dropdowns
        for (let i = 0; i < 6; i++) {
            const select = document.getElementById('program-' + i);
            if (select) {
                select.innerHTML = '<option value="">— App auswählen —</option>';
                apps.forEach(app => {
                    const opt = document.createElement('option');
                    opt.value = app;
                    opt.textContent = app;
                    select.appendChild(opt);
                });
            }
        }
    } catch (e) {
        console.error('Failed to load apps:', e);
    }
}

function loadPrograms(programs) {
    // Load saved programs into dropdowns (handle both null and undefined)
    for (let i = 0; i < 6; i++) {
        const select = document.getElementById('program-' + i);
        if (select) {
            const app = programs && programs[i];
            select.value = app || '';
        }
    }
}

async function saveConfig() {
    const btn = document.querySelector('.btn-primary');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '…';
    // Collect all 6 program slots (including empty ones, storing null for empty)
    const programs = [];
    for (let i = 0; i < 6; i++) {
        const select = document.getElementById('program-' + i);
        if (select) {
            programs.push(select.value || null);
        } else {
            programs.push(null);
        }
    }

    // Use selected voice or fallback to current/default if dropdown is empty
    const voiceId = voiceDb.active_voice_id
        || currentConfig.elevenlabs_voice_id
        || 'rDmv3mOhK6TnhYWckFaD';

    const config = {
        anthropic_api_key: document.getElementById('anthropicKey').value,
        elevenlabs_api_key: document.getElementById('elevenlabsKey').value,
        elevenlabs_voice_id: voiceId,
        user_name: document.getElementById('userName').value,
        user_address: document.getElementById('userAddress').value,
        city: document.getElementById('city').value,
        timezone: document.getElementById('timezone').value,
        lat: parseFloat(document.getElementById('lat').value),
        lon: parseFloat(document.getElementById('lon').value),
        kachelmann_api_key: document.getElementById('kachelmannKey').value,
        workspace_path: document.getElementById('workspacePath').value,
        obsidian_inbox_path: document.getElementById('obsidianPath').value,
        ha_url: document.getElementById('haUrl').value,
        ha_token: document.getElementById('haToken').value,
        ha_enabled: document.getElementById('haToggle').classList.contains('on'),
        browser_url: document.getElementById('browserUrl').value,
        spotify_track: document.getElementById('spotifyTrack').value,
        wake_greeting_enabled: document.getElementById('wakeGreetingToggle').classList.contains('on'),
        programs: programs
    };

    try {
        const resp = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });

        const data = await resp.json();
        if (data.status === 'saved' && (!data.errors || data.errors.length === 0)) {
            btn.textContent = '✓ Gespeichert';
            btn.style.background = '#4cbf7e';
            showToast('Einstellungen gespeichert', 'success');
        } else {
            const errorMsg = data.errors && data.errors.length > 0 ? data.errors[0] : 'Fehler beim Speichern';
            btn.textContent = '✗ Fehler';
            btn.style.background = '#e05252';
            showToast(errorMsg, 'error');
        }
    } catch (e) {
        btn.textContent = '✗ Fehler';
        btn.style.background = '#e05252';
        showToast('Speichern fehlgeschlagen: ' + e.message, 'error');
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = original;
            btn.style.background = '';
        }, 2500);
    }
}

function loadDefaults() {
    if (confirm('Wirklich auf Standardwerte zurücksetzen?')) {
        fetch('/api/reset_config', {method: 'POST'}).then(() => {
            loadConfig();
            showToast('Standardwerte geladen', 'success');
        });
    }
}

function restart() {
    document.getElementById('restartModal').classList.add('show');
}

function closeModal() {
    document.getElementById('restartModal').classList.remove('show');
}

async function confirmRestart() {
    closeModal();
    showToast('Server wird neu gestartet…', 'success');
    await fetch('/api/restart', {method: 'POST'}).catch(() => {});
    setTimeout(() => location.reload(), 2000);
}

function toggleVisibility(fieldId, btn) {
    const input = document.getElementById(fieldId);
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    btn.textContent = isHidden ? '🙈' : '👁';
    btn.title = isHidden ? 'Key verstecken' : 'Key anzeigen';
}

function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast show ' + type;
    setTimeout(() => toast.classList.remove('show'), 3000);
}
