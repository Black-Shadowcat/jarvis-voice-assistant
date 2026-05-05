// Load config on page load
document.addEventListener('DOMContentLoaded', loadConfig);

let currentConfig = {};

async function loadConfig() {
    try {
        const resp = await fetch('/api/config');
        const data = await resp.json();
        currentConfig = data;

        // Fill form fields
        document.getElementById('anthropicKey').value = data.anthropic_api_key || '';
        document.getElementById('elevenlabsKey').value = data.elevenlabs_api_key || '';
        document.getElementById('voiceSelect').value = data.elevenlabs_voice_id || '';
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

        // Load voices
        await loadVoices();

        // Load available apps and populate dropdowns
        await loadAvailableApps();

        // Load selected programs
        loadPrograms(data.programs || []);

    } catch (e) {
        console.error('Config load failed:', e);
    }
}

async function loadVoices() {
    try {
        const resp = await fetch('/api/elevenlabs_voices');
        const data = await resp.json();
        const select = document.getElementById('voiceSelect');
        const currentVoice = currentConfig.elevenlabs_voice_id || '';
        const count = data.voices?.length || 0;
        document.getElementById('voiceCount').textContent = `${count} Voices geladen`;

        if (data.voices) {
            data.voices.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.voice_id;
                opt.textContent = v.name;
                select.appendChild(opt);
            });
            // Set the current voice after populating
            if (currentVoice) {
                select.value = currentVoice;
            }
        }
    } catch (e) {
        console.error('Voices load failed:', e);
    }
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

async function previewVoice() {
    const voiceId = document.getElementById('voiceSelect').value;
    if (!voiceId) {
        showToast('Voice auswählen', 'error');
        return;
    }

    try {
        const resp = await fetch('/api/preview_voice', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({voice_id: voiceId})
        });

        const data = await resp.json();
        if (data.audio) {
            const audio = new Audio('data:audio/mpeg;base64,' + data.audio);
            audio.play();
            showToast('Voice-Vorschau wird abgespielt', 'success');
        }
    } catch (e) {
        showToast('Vorschau fehlgeschlagen', 'error');
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
    let voiceId = document.getElementById('voiceSelect').value;
    if (!voiceId && currentConfig.elevenlabs_voice_id) {
        voiceId = currentConfig.elevenlabs_voice_id;
    }
    if (!voiceId) {
        voiceId = 'rDmv3mOhK6TnhYWckFaD'; // Default voice ID fallback
    }

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
            showToast('Einstellungen gespeichert', 'success');
        } else {
            const errorMsg = data.errors && data.errors.length > 0 ? data.errors[0] : 'Fehler beim Speichern';
            showToast(errorMsg, 'error');
        }
    } catch (e) {
        showToast('Speichern fehlgeschlagen: ' + e.message, 'error');
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

function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast show ' + type;
    setTimeout(() => toast.classList.remove('show'), 3000);
}
