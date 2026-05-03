// Jarvis V2 — Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');
const muteBtn = document.getElementById('mute-btn');

let ws;
let audioQueue = [];
let isPlaying = false;
let audioUnlocked = false;
let isMuted = false;
let audioEndTime = 0;

// Mute button functionality
muteBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    isMuted = !isMuted;
    muteBtn.textContent = isMuted ? '🔇' : '🎤';
    muteBtn.title = isMuted ? 'Mikrofon einschalten' : 'Mikrofon auschalten';
    muteBtn.style.opacity = isMuted ? '0.5' : '1';
    if (isMuted && isListening) {
        recognition.stop();
        isListening = false;
    }
});

// Unlock audio on ANY user interaction
function unlockAudio() {
    if (!audioUnlocked) {
        const silent = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA');
        silent.play().then(() => {
            audioUnlocked = true;
            console.log('[jarvis] Audio unlocked');
        }).catch(() => {});
        // Pre-warm microphone permission on first click so Safari shows the dialog
        // here (on explicit user gesture) instead of mid-sentence later.
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(stream => stream.getTracks().forEach(t => t.stop()))
                .catch(() => {});
        }
    }
}
document.addEventListener('click', unlockAudio, { once: false });
document.addEventListener('touchstart', unlockAudio, { once: false });
document.addEventListener('keydown', unlockAudio, { once: false });

function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => {
        console.log('[jarvis] WebSocket connected');
        status.textContent = 'Klicke einmal irgendwo, dann spricht Jarvis.';
        setOrbState('thinking');
        ws.send(JSON.stringify({ text: 'Jarvis activate' }));
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'response') {
            addTranscript('jarvis', data.text);
            if (data.audio && data.audio.length > 0) {
                queueAudio(data.audio);
            } else {
                setOrbState('idle');
                setTimeout(startListening, 1200);
            }
        } else if (data.type === 'status') {
            status.textContent = data.text;
        }
    };
    ws.onclose = () => {
        status.textContent = 'Verbindung verloren...';
        setTimeout(connect, 3000);
    };
}

function queueAudio(base64Audio) {
    audioQueue.push(base64Audio);
    if (!isPlaying) playNext();
}

function playNext() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        audioEndTime = Date.now();
        setOrbState('listening');
        status.textContent = '';
        setTimeout(startListening, 1200);
        return;
    }
    isPlaying = true;
    setOrbState('speaking');
    status.textContent = '';
    if (isListening) {
        recognition.stop();
        isListening = false;
    }

    const b64 = audioQueue.shift();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => { URL.revokeObjectURL(url); playNext(); };
    audio.onerror = () => { URL.revokeObjectURL(url); playNext(); };
    audio.play().catch(err => {
        console.warn('[jarvis] Autoplay blocked, waiting for click...');
        status.textContent = 'Klicke irgendwo damit Jarvis sprechen kann.';
        setOrbState('idle');
        // Wait for click then retry
        document.addEventListener('click', function retry() {
            document.removeEventListener('click', retry);
            audio.play().then(() => {
                setOrbState('speaking');
                status.textContent = '';
            }).catch(() => playNext());
        });
    });
}

// Speech Recognition
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let isListening = false;

// Korrektur bekannter Fehlerkennungen der Web Speech API
const SPEECH_CORRECTIONS = {
    'ob sie dir': 'Obsidian',
    'ob si dir': 'Obsidian',
    'ob sie di': 'Obsidian',
    'obsidian': 'Obsidian',
};

function correctTranscript(text) {
    let t = text;
    for (const [wrong, right] of Object.entries(SPEECH_CORRECTIONS)) {
        t = t.replace(new RegExp(wrong, 'gi'), right);
    }
    return t;
}

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'de-DE';
    recognition.continuous = true;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        if (isPlaying || Date.now() - audioEndTime < 2000) return;
        const last = event.results[event.results.length - 1];
        if (last.isFinal) {
            const text = correctTranscript(last[0].transcript.trim());
            if (text) {
                addTranscript('user', text);
                setOrbState('thinking');
                status.textContent = 'Jarvis denkt nach...';
                ws.send(JSON.stringify({ text }));
            }
        }
    };

    recognition.onend = () => {
        isListening = false;
        if (!isPlaying) setTimeout(startListening, 300);
    };

    recognition.onerror = (event) => {
        isListening = false;
        if (event.error === 'no-speech' || event.error === 'aborted') {
            if (!isPlaying) setTimeout(startListening, 300);
        } else {
            setTimeout(startListening, 1000);
        }
    };
}

function startListening() {
    if (isPlaying) return;
    if (isMuted) return;  // Don't start if muted
    try {
        recognition.start();
        isListening = true;
        setOrbState('listening');
        status.textContent = '';
    } catch(e) {}
}

orb.addEventListener('click', () => {
    if (isPlaying) return;
    if (isMuted) {
        status.textContent = 'Mikrofon ist stumm. Klicke auf 🎤 um zu aktivieren.';
        return;
    }
    if (isListening) {
        recognition.stop();
        isListening = false;
        setOrbState('idle');
        status.textContent = 'Pausiert. Klicke zum Fortsetzen.';
    } else {
        startListening();
    }
});

function setOrbState(state) { orb.className = state; }

function addTranscript(role, text) {
    const div = document.createElement('div');
    div.className = role;
    div.textContent = role === 'user' ? `Du: ${text}` : `Jarvis: ${text}`;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

connect();
