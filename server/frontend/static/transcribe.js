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
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        socket = new WebSocket(`${protocol}://${window.location.host}/v1/${team_slug}/mates/call`);

        socket.binaryType = 'arraybuffer';

        socket.onopen = () => {
            console.log('WebSocket connection opened.');

            // Set the onmessage handler after the connection is opened
            socket.onmessage = async (event) => {
                if (typeof event.data === 'string') {
                    const response = JSON.parse(event.data);
                    if (response.type === 'response.audio.delta' && response.audio) {
                        const audioData = base64ToArrayBuffer(response.audio);
                        await playAudio(audioData);
                    }
                } else {
                    await playAudio(event.data);
                }
            };
        };

        socket.onerror = (error) => {
            console.error('WebSocket error:', error);
            alert('WebSocket connection error. Check console for details.');
            stopRecording();
        };

        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            const inputData = e.inputBuffer.getChannelData(0);
            const int16Data = convertFloat32ToInt16(inputData);
            if (socket && socket.readyState === WebSocket.OPEN) {  // Added null check for socket
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

    if (socket) {
        socket.close();
        socket = null;
    }
}

function convertFloat32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        let s = Math.max(-1, Math.min(1, float32Array[i]));
        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
}

function base64ToArrayBuffer(base64) {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
}

let audioQueue = [];
let isPlaying = false;

async function playAudio(arrayBuffer) {
    audioQueue.push(arrayBuffer);
    if (!isPlaying) {
        playNextInQueue();
    }
}

async function playNextInQueue() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        return;
    }

    isPlaying = true;
    const arrayBuffer = audioQueue.shift();

    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    try {
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        source.onended = playNextInQueue;
        source.start(0);
    } catch (error) {
        console.error('Error decoding audio data:', error);
        playNextInQueue();
    }
}