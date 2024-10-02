const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const statusDiv = document.getElementById('status');

let mediaStream = null;
let audioContext = null;
let processor = null;
let socket = null;

startBtn.addEventListener('click', startRecording);
stopBtn.addEventListener('click', stopRecording);

const team_slug = 'test';

async function startRecording() {
    startBtn.disabled = true;
    stopBtn.disabled = false;
    statusDiv.textContent = 'Recording...';

    try {
        // Initialize WebSocket connection
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        socket = new WebSocket(`${protocol}://${window.location.host}/v1/${team_slug}/mates/call`);

        socket.binaryType = 'arraybuffer';

        socket.onopen = () => {
            console.log('WebSocket connection opened.');
        };

        socket.onerror = (error) => {
            console.error('WebSocket error:', error);
            alert('WebSocket connection error. Check console for details.');
            stopRecording();
        };

        // Get user audio
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            const inputData = e.inputBuffer.getChannelData(0);
            const int16Data = convertFloat32ToInt16(inputData);
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(int16Data.buffer);
            }
        };
    } catch (err) {
        console.error('Error accessing audio devices:', err);
        alert('Could not access microphone. Please check permissions.');
        startBtn.disabled = false;
        stopBtn.disabled = true;
        statusDiv.textContent = 'Not Recording';
    }
}

function stopRecording() {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    statusDiv.textContent = 'Not Recording';

    // Stop audio processing
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }

    // Close WebSocket connection
    if (socket) {
        socket.close();
        socket = null;
    }
}

// Helper function to convert Float32Array to Int16Array
function convertFloat32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        let s = Math.max(-1, Math.min(1, float32Array[i]));
        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
}