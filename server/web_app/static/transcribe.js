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

let isResponsePlaying = false;
let shouldStopProcessing = false;

// voice call still isn't working properly. Ignores when the user is interrupting the AI voice.

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
                        if (!shouldStopProcessing) {
                            isResponsePlaying = true;
                            await playAudio(audioData);
                        }
                    } else if (response.type === 'stop_audio') {
                        await stopAudioPlayback();
                    } else if (response.type === 'end_of_response') {
                        isResponsePlaying = false;
                        shouldStopProcessing = false;
                    }
                } else {
                    if (!shouldStopProcessing) {
                        isResponsePlaying = true;
                        await playAudio(event.data);
                    }
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
            if (socket && socket.readyState === WebSocket.OPEN) {
                if (isResponsePlaying) {
                    socket.send(JSON.stringify({ type: 'interrupt' }));
                    stopAudioPlayback();
                    shouldStopProcessing = true;
                }
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
let currentSource = null;  // Track the current audio source
let playbackAudioContext = null;  // Separate audio context for playback

async function playAudio(arrayBuffer) {
    audioQueue.push(arrayBuffer);
    if (!isPlaying) {
        playNextInQueue();
    }
}

async function playNextInQueue() {
    if (audioQueue.length === 0 || shouldStopProcessing) {
        isPlaying = false;
        return;
    }

    isPlaying = true;
    const arrayBuffer = audioQueue.shift();

    if (!playbackAudioContext || playbackAudioContext.state === 'closed') {
        playbackAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    try {
        const audioBuffer = await playbackAudioContext.decodeAudioData(arrayBuffer);
        const source = playbackAudioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(playbackAudioContext.destination);
        source.onended = () => {
            currentSource = null;  // Clear the current source when playback ends
            if (!shouldStopProcessing) {
                playNextInQueue();
            }
        };
        currentSource = source;  // Track the current source
        source.start(0);
    } catch (error) {
        console.error('Error decoding audio data:', error);
        if (!shouldStopProcessing) {
            playNextInQueue();
        }
    }
}

async function stopAudioPlayback() {
    console.log('Stopping audio playback');
    audioQueue = [];
    isPlaying = false;
    isResponsePlaying = false;
    if (currentSource) {
        currentSource.stop();  // Stop the current audio source
        currentSource.disconnect();
        currentSource = null;
    }
    if (playbackAudioContext) {
        await playbackAudioContext.close();
        playbackAudioContext = null;
    }
}