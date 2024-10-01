// frontend/static/call.js

const domain = window.location.origin;
const mateName = window.location.pathname.split('/')[2];

const localVideo = document.getElementById('localVideo');
const toggleVideoBtn = document.getElementById('toggleVideo');
const recordBtn = document.getElementById('recordButton');
const recordIndicator = document.getElementById('recordIndicator');

let videoEnabled = true;
let recording = false;
let stream;
let mediaRecorder;
let socket;

// Initialize Media Streams and WebSocket
async function initMedia() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        localVideo.srcObject = stream;
        setupWebSocket();
    } catch (err) {
        console.error('Error accessing media devices.', err);
    }
}

// Toggle Video
toggleVideoBtn.addEventListener('click', () => {
    videoEnabled = !videoEnabled;
    const videoTrack = stream.getVideoTracks()[0];
    videoTrack.enabled = videoEnabled;
    toggleVideoBtn.textContent = videoEnabled ? 'Turn Video Off' : 'Turn Video On';
});

// Handle Recording
recordBtn.addEventListener('click', () => {
    recording = !recording;
    if (recording) {
        recordBtn.textContent = 'Stop Recording';
        recordIndicator.classList.add('glowing');
        startImageCapture();
    } else {
        recordBtn.textContent = 'Start Recording';
        recordIndicator.classList.remove('glowing');
        stopImageCapture();
    }
});

let imageInterval;

// Capture and Send Images Every 500ms
function startImageCapture() {
    imageInterval = setInterval(() => {
        captureImage();
    }, 500);
}

function stopImageCapture() {
    clearInterval(imageInterval);
}

// Capture Image from Video and Send to Server
async function captureImage() {
    const canvas = document.createElement('canvas');
    canvas.width = localVideo.videoWidth;
    canvas.height = localVideo.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(localVideo, 0, 0, canvas.width, canvas.height);
    const imageData = canvas.toDataURL('image/jpeg');

    await fetch(`${domain}/mates/${mateName}/upload_image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: imageData }),
    });
}

// Setup WebSocket for Audio Streaming and Receiving Voice Responses
function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(`${protocol}://${window.location.host}/ws/mates/${mateName}/audio`);

    socket.onopen = () => {
        console.log('WebSocket connection established.');
        startAudioStream();
    };

    socket.onmessage = (event) => {
        // Assuming the server sends voice data as a blob URL
        const data = JSON.parse(event.data);
        if (data.voice && data.voice_url) {
            playVoice(data.voice_url);
        }
    };

    socket.onclose = () => {
        console.log('WebSocket connection closed.');
    };

    socket.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// Audio Streaming to Server using MediaRecorder
function startAudioStream() {
    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
        console.error('No audio track available.');
        return;
    }

    const options = { mimeType: 'audio/webm; codecs=opus' };
    mediaRecorder = new MediaRecorder(new MediaStream(audioTracks), options);

    mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
            const arrayBuffer = await event.data.arrayBuffer();
            socket.send(arrayBuffer);
        }
    };

    mediaRecorder.start(250); // Send audio chunks every 250ms
}

function playVoice(voiceBlobUrl) {
    const audio = new Audio();
    audio.src = voiceBlobUrl;
    audio.play();
}

// Initialize
initMedia();