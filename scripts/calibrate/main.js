window.addEventListener('load', () => {
    const cachedData = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (cachedData) { try { data = JSON.parse(cachedData); } catch(e) { resetDataStructure(); } }
    else { resetDataStructure(); }

    updateTextarea();

    fetch('/api/video_meta')
        .then(res => res.json())
        .then(meta => {
            const telemetryElement = document.getElementById('metaTelemetryContent');
            if (telemetryElement) {
                telemetryElement.innerHTML = `File: ${meta.filename}<br>Res:  ${meta.width}x${meta.height}<br>Rate: ${meta.fps} FPS<br>Span: ${meta.duration_seconds.toFixed(1)}s (~${meta.total_estimated_frames} frames)`;
            }
            viewGeom.nativeW = meta.width; viewGeom.nativeH = meta.height;

            if (data.near_basket && data.near_basket.attacked_by) document.getElementById('selNearAttackedBy').value = data.near_basket.attacked_by;
            if (data.far_basket && data.far_basket.attacked_by) document.getElementById('selFarAttackedBy').value = data.far_basket.attacked_by;

            resizeCanvas();
        })
        .catch(err => { resizeCanvas(); });
});

window.addEventListener('resize', resizeCanvas);
const videoCoreElement = document.getElementById('videoCore');
if (videoCoreElement) {
    videoCoreElement.addEventListener('loadedmetadata', () => { resizeCanvas(); updatePlaybackTimeline(); });
    videoCoreElement.addEventListener('timeupdate', () => {
        // Automatically append updated head timestamps onto active indices during scrubber interaction
        if (currentPhase === 'ball' && editingBallIdx !== null && data.ball_samples[editingBallIdx]) {
            data.ball_samples[editingBallIdx].timestamp = videoCoreElement.currentTime;
            updateTextarea();
        }
        else if (currentPhase === 'seeding' && editingPlayerIdx !== null && data.player_seeds[editingPlayerIdx]) {
            data.player_seeds[editingPlayerIdx].box.timestamp = videoCoreElement.currentTime;
            updateTextarea();
        }
        updatePlaybackTimeline();
    });
}

const targetOverlayCanvas = document.getElementById('overlayCanvas');
if (targetOverlayCanvas) {
    targetOverlayCanvas.addEventListener('mousedown', (e) => {
        const videoElement = document.getElementById('videoCore');
        const playbackButton = document.getElementById('playBtn');
        if (videoElement) videoElement.pause();
        if (playbackButton) playbackButton.textContent = "Play";
        const coords = getRelativeImageCoords(e);
        if (currentPhase === 'boundaries') {
            if (data.court_corners.length >= 4) { data.court_corners = []; }
            data.court_corners.push({ x: coords.x, y: coords.y }); updateTextarea(); draw(); return;
        }
        isDrawing = true; dragStart = coords; currentMouse = { x: coords.x, y: coords.y };
    });

    targetOverlayCanvas.addEventListener('mousemove', (e) => {
        if (!isDrawing) return;
        const coords = getRelativeImageCoords(e); currentMouse.x = coords.x; currentMouse.y = coords.y; draw();
    });

    targetOverlayCanvas.addEventListener('mouseup', (e) => {
        if (!isDrawing) return; isDrawing = false;
        const videoElement = document.getElementById('videoCore');
        const box = {
            x: Math.min(dragStart.x, currentMouse.x), y: Math.min(dragStart.y, currentMouse.y),
            w: Math.abs(currentMouse.x - dragStart.x), h: Math.abs(currentMouse.y - dragStart.y),
            timestamp: videoElement ? videoElement.currentTime : 0
        };
        if (box.w < 3 || box.h < 3) return;

        if (currentPhase === 'boundaries') { data.substitution_zone = box; }
        else if (currentPhase === 'rims') {
            if (!data.near_basket) {
                box.attacked_by = document.getElementById('selNearAttackedBy').value;
                data.near_basket = box;
            }
            else if (!data.far_basket) {
                box.attacked_by = document.getElementById('selFarAttackedBy').value;
                data.far_basket = box;
            }
        }
        // Snippet reference replacement target for mouseup event layer inside main.js:
        else if (currentPhase === 'seeding') {
            if (editingPlayerIdx !== null && data.player_seeds[editingPlayerIdx]) {
                const targetChar = data.player_seeds[editingPlayerIdx];
                if (!targetChar.boxes) targetChar.boxes = [];

                // Append bounding coordinates straight onto one-to-many child structures
                targetChar.boxes.push(box);
                editingPlayerBoxIdx = targetChar.boxes.length - 1;
            } else {
                alert("Please click 'New' inside the Identity panel to create or select a character profile parent node first.");
                return;
            }
        }
        else if (currentPhase === 'ball') {
            if (editingBallIdx !== null && data.ball_samples[editingBallIdx]) {
                data.ball_samples[editingBallIdx].box = box;
            } else {
                data.ball_samples.push({ box, status: "clear", timestamp: videoElement.currentTime, court_x: 50, court_y: 50 });
                editingBallIdx = data.ball_samples.length - 1;
            } enterBallEditMode(editingBallIdx);
        }
        updateTextarea(); draw();
    });
}