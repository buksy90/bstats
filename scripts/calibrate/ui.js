// =====================================================================
// 📺 WORKSPACE CANVAS & VIEWPORT RENDERING RESIZER
// =====================================================================
function resizeCanvas() {
    const video = document.getElementById('videoCore');
    const canvas = document.getElementById('overlayCanvas');
    const videoWrapper = document.getElementById('videoWrapper');
    const zoomSelect = document.getElementById('zoomSelect');

    if (!video || !canvas || !videoWrapper) return;

    const zoom = parseFloat(zoomSelect.value || 1.0);
    const parentWidth = document.querySelector('.workspace-block').clientWidth - 30;
    const nativeRatio = viewGeom.nativeW / viewGeom.nativeH;
    const targetWidth = parentWidth * zoom;

    videoWrapper.style.width = targetWidth + 'px';
    videoWrapper.style.height = (targetWidth / nativeRatio) + 'px';

    canvas.width = videoWrapper.clientWidth;
    canvas.height = videoWrapper.clientHeight;

    viewGeom.dispW = canvas.width;
    viewGeom.dispH = canvas.height;
    viewGeom.offsetX = 0;
    viewGeom.offsetY = 0;

    draw();
}

// =====================================================================
// 🕹️ VIDEO CONTROLS & TIMELINE SYNCHRONIZATION
// =====================================================================
function togglePlayback() {
    const video = document.getElementById('videoCore');
    const playBtn = document.getElementById('playBtn');
    if (video.paused) { video.play(); playBtn.textContent = "Pause"; }
    else { video.pause(); playBtn.textContent = "Play"; }
}

// Fixed: Utilizes global standard Math context wrapper directly to resolve min() exceptions
function adjustTime(seconds) {
    const video = document.getElementById('videoCore');
    video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
}

function seekVideo() {
    const video = document.getElementById('videoCore');
    const slider = document.getElementById('timelineSlider');
    video.currentTime = (slider.value / 100) * video.duration;
}

function updatePlaybackTimeline() {
    const video = document.getElementById('videoCore');
    const slider = document.getElementById('timelineSlider');
    const timeDisplay = document.getElementById('timeDisplay');

    if (!video || !video.duration) return;
    slider.value = (video.currentTime / video.duration) * 100;
    timeDisplay.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
    draw();
}

// =====================================================================
// 🧭 PHASE WORKFLOW ROUTER STATE SELECTION
// =====================================================================
function switchPhase(targetPhase) {
    currentPhase = targetPhase;
    document.querySelectorAll('.phase-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`pbtn_${targetPhase}`).classList.add('active');

    document.getElementById('basketPanel').style.display = (targetPhase === 'rims') ? 'block' : 'none';
    document.getElementById('registryPanel').style.display = (targetPhase === 'seeding') ? 'block' : 'none';
    document.getElementById('ballPanel').style.display = (targetPhase === 'ball') ? 'block' : 'none';
    document.getElementById('minimapDot').style.display = 'none';

    exitBallEditMode();
    exitPlayerEditMode();

    const instrTitle = document.getElementById('instructionTitle');
    const instrText = document.getElementById('instructionText');

    if (targetPhase === 'boundaries') {
        instrTitle.textContent = "Phase 1: Court & Substitution Setup";
        instrText.textContent = "Click 4 corners sequentially clockwise to define the court vector field. Afterward, click and drag a boundary bounding box mapping out the team substitution bench area.";
    } else if (targetPhase === 'rims') {
        instrTitle.textContent = "Phase 2: Basket Hoop Calibration";
        instrText.textContent = "Click and drag your first bounding box directly around the NEAR basket hoop, then click and drag your secondary box surrounding the FAR basket hoop layout location.";
    } else if (targetPhase === 'seeding') {
        instrTitle.textContent = "Phase 3: Ground Truth Identity Seeding";
        instrText.textContent = "Click 'New' to instantiate a profile token. While active, any boxes drawn on screen add historical time-gated sample nodes directly inside that character's registry track.";
        if (data.player_seeds && data.player_seeds.length > 0) enterPlayerEditMode(0);
    } else if (targetPhase === 'ball') {
        instrTitle.textContent = "Phase 4: Spatial Ball Range Sampling";
        instrText.textContent = "Choose a target sample slice from the dropdown selector matrix or click Add to allocate fresh baseline measurement bounding boundaries on current frames.";
        if (data.ball_samples && data.ball_samples.length > 0) enterBallEditMode(0);
    }
    draw();
}

// =====================================================================
// 🎯 TACTICAL RIM & HOOP SELECTIONS
// =====================================================================
function updateBasketTeamAssignments() {
    if (data.near_basket) data.near_basket.attacked_by = document.getElementById('selNearAttackedBy').value;
    if (data.far_basket) data.far_basket.attacked_by = document.getElementById('selFarAttackedBy').value;
    updateTextarea();
}

function clearBasketBoxes() {
    data.near_basket = null; data.far_basket = null;
    updateTextarea(); draw();
}

// =====================================================================
// 👥 IDENTITY REGISTRY HANDLERS (ONE-TO-MANY RELATIONAL DESIGN)
// =====================================================================
function handlePlayerSelectChange() {
    const val = document.getElementById('selPlayerSeed').value;
    if (val === "") { exitPlayerEditMode(); return; }
    enterPlayerEditMode(parseInt(val, 10));
}

function enterPlayerEditMode(idx) {
    editingPlayerIdx = idx;
    editingPlayerBoxIdx = null;

    const p = data.player_seeds[idx];
    if (p) {
        document.getElementById('selTeam').value = p.team;
        if (p.boxes && p.boxes.length > 0) {
            handlePlayerBoxSelect(0);
            return;
        }
    }
    updateTextarea();
    draw();
}

function exitPlayerEditMode() {
    editingPlayerIdx = null;
    editingPlayerBoxIdx = null;
    updateTextarea();
    draw();
}

function addNewPlayerSeedPrompt() {
    const name = prompt("Enter unique name identifier token for new character profile:");
    if (!name || name.trim() === "") return;

    const newSeed = {
        name: name.trim(),
        team: document.getElementById('selTeam').value || "light",
        boxes: []
    };

    if (!data.player_seeds) data.player_seeds = [];
    data.player_seeds.push(newSeed);

    editingPlayerIdx = data.player_seeds.length - 1;
    editingPlayerBoxIdx = null;
    updateTextarea();
}

function deleteEntireCharacter() {
    if (editingPlayerIdx === null || !data.player_seeds[editingPlayerIdx]) return;
    if (!confirm(`Are you sure you want to completely wipe character profile "${data.player_seeds[editingPlayerIdx].name}" along with all stored boxes?`)) return;

    data.player_seeds.splice(editingPlayerIdx, 1);
    const fallback = data.player_seeds.length - 1;
    if (fallback >= 0) enterPlayerEditMode(fallback);
    else exitPlayerEditMode();
}

function handlePlayerTeamChange() {
    if (editingPlayerIdx === null || !data.player_seeds[editingPlayerIdx]) return;
    data.player_seeds[editingPlayerIdx].team = document.getElementById('selTeam').value;
    updateTextarea();
}

function handlePlayerBoxSelect(boxIdx) {
    if (editingPlayerIdx === null || !data.player_seeds[editingPlayerIdx]) return;
    editingPlayerBoxIdx = boxIdx;

    const box = data.player_seeds[editingPlayerIdx].boxes[boxIdx];
    const video = document.getElementById('videoCore');
    if (box && video) {
        video.currentTime = box.timestamp;
    }
    renderIdentityList();
    draw();
}

function deletePlayerBoxIndex(boxIdx) {
    if (editingPlayerIdx === null || !data.player_seeds[editingPlayerIdx]) return;
    data.player_seeds[editingPlayerIdx].boxes.splice(boxIdx, 1);
    editingPlayerBoxIdx = null;
    updateTextarea();
}

// =====================================================================
// 🏀 SPATIAL BALL RANGE HANDLERS
// =====================================================================
function handleBallSelectChange() {
    const val = document.getElementById('selBallSample').value;
    if (val === "") { exitBallEditMode(); return; }
    const idx = parseInt(val, 10);
    enterBallEditMode(idx);

    const video = document.getElementById('videoCore');
    if (data.ball_samples[idx] && video) video.currentTime = data.ball_samples[idx].timestamp;
}

function enterBallEditMode(idx) {
    editingBallIdx = idx;
    document.getElementById('ballPanelTitle').textContent = `Spatial HSV Range (Editing Sample #${idx + 1})`;

    const b = data.ball_samples[idx];
    const minimapDot = document.getElementById('minimapDot');
    if (b && b.court_x !== undefined) {
        minimapDot.style.left = `${b.court_x}%`; minimapDot.style.top = `${b.court_y}%`;
        minimapDot.style.display = 'block';
    } else { minimapDot.style.display = 'none'; }
    populateBallDropdown();
    draw();
}

function exitBallEditMode() {
    editingBallIdx = null;
    document.getElementById('ballPanelTitle').textContent = "Spatial HSV Range Swatches (Clear Only)";
    document.getElementById('minimapDot').style.display = 'none';
    populateBallDropdown();
    draw();
}

function addNewBlankBallSample() {
    const video = document.getElementById('videoCore');
    const newSample = {
        box: { x: 910, y: 490, w: 100, h: 100, timestamp: video.currentTime },
        status: "clear",
        timestamp: video.currentTime,
        court_x: 50, court_y: 50
    };
    if (!data.ball_samples) data.ball_samples = [];
    data.ball_samples.push(newSample);
    editingBallIdx = data.ball_samples.length - 1;
    updateTextarea();
    enterBallEditMode(editingBallIdx);
}

function confirmBallClassification(statusType) {
    if (editingBallIdx === null || !data.ball_samples[editingBallIdx]) return;
    data.ball_samples[editingBallIdx].status = statusType;

    // STRATEGY ENFORCEMENT: Output structural profile logging parameters straight to developer console terminal
    console.log(`[Ball Swatch Classification Saved] Index Matrix Key #${editingBallIdx}:`, JSON.parse(JSON.stringify(data.ball_samples[editingBallIdx])));

    updateTextarea(); recomputeGlobalHsv(); draw();
}

function deleteCurrentEditedBall() {
    if (editingBallIdx === null) return;
    data.ball_samples.splice(editingBallIdx, 1);
    const fallbackIdx = data.ball_samples.length - 1;
    if (fallbackIdx >= 0) enterBallEditMode(fallbackIdx);
    else exitBallEditMode();
    updateTextarea(); recomputeGlobalHsv(); draw();
}

function handleMinimapClickOverride(e) {
    if (currentPhase !== 'ball' || editingBallIdx === null || !data.ball_samples[editingBallIdx]) return;
    const rect = document.getElementById('minimapContainer').getBoundingClientRect();
    const clickX_pct = Math.round(((e.clientX - rect.left) / rect.width) * 100);
    const clickY_pct = Math.round(((e.clientY - rect.top) / rect.height) * 100);

    data.ball_samples[editingBallIdx].court_x = clickX_pct;
    data.ball_samples[editingBallIdx].court_y = clickY_pct;

    const minimapDot = document.getElementById('minimapDot');
    minimapDot.style.left = `${clickX_pct}%`; minimapDot.style.top = `${clickY_pct}%`;
    minimapDot.style.display = 'block';
    updateTextarea();
}

// =====================================================================
// 🖌️ VERTEX GRAPHICS VECTOR CANVAS RENDER LOOP CORE
// =====================================================================
function draw() {
    const canvas = document.getElementById('overlayCanvas');
    const video = document.getElementById('videoCore');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Phase 1 Isolation Guard Loop
    if (currentPhase === 'boundaries') {
        if (data.court_corners && data.court_corners.length > 0) {
            ctx.strokeStyle = '#0070f3'; ctx.lineWidth = 2; ctx.fillStyle = '#0070f3';
            ctx.font = "bold 14px -apple-system, sans-serif";
            data.court_corners.forEach((pt, idx) => {
                const cx = toScreenX(pt.x); const cy = toScreenY(pt.y);
                ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 2 * Math.PI); ctx.fill();
                ctx.fillText(String(idx + 1), cx + 8, cy - 8);
            });
            ctx.beginPath();
            data.court_corners.forEach((pt, idx) => {
                if (idx === 0) ctx.moveTo(toScreenX(pt.x), toScreenY(pt.y));
                else ctx.lineTo(toScreenX(pt.x), toScreenY(pt.y));
            });
            if (data.court_corners.length === 4) ctx.closePath();
            ctx.stroke();
        }
        if (data.substitution_zone) {
            const sx = toScreenX(data.substitution_zone.x); const sy = toScreenY(data.substitution_zone.y);
            ctx.strokeStyle = '#9b59b6'; ctx.lineWidth = 2;
            ctx.strokeRect(sx, sy, toScreenW(data.substitution_zone.w), toScreenH(data.substitution_zone.h));
            ctx.fillStyle = 'rgba(155, 89, 182, 0.1)'; ctx.fillRect(sx, sy, toScreenW(data.substitution_zone.w), toScreenH(data.substitution_zone.h));
        }
        return;
    }

    // Phase 2 Isolation Guard Loop
    if (currentPhase === 'rims') {
        ctx.font = "bold 12px monospace";
        if (data.near_basket) {
            ctx.strokeStyle = '#28a745'; ctx.lineWidth = 2; ctx.fillStyle = '#28a745';
            const sx = toScreenX(data.near_basket.x); const sy = toScreenY(data.near_basket.y);
            ctx.strokeRect(sx, sy, toScreenW(data.near_basket.w), toScreenH(data.near_basket.h));
            ctx.fillText(`NEAR RIM (${data.near_basket.attacked_by || 'dark'})`, sx, sy - 4);
        }
        if (data.far_basket) {
            ctx.strokeStyle = '#dc3545'; ctx.lineWidth = 2; ctx.fillStyle = '#dc3545';
            const sx = toScreenX(data.far_basket.x); const sy = toScreenY(data.far_basket.y);
            ctx.strokeRect(sx, sy, toScreenW(data.far_basket.w), toScreenH(data.far_basket.h));
            ctx.fillText(`FAR RIM (${data.far_basket.attacked_by || 'light'})`, sx, sy - 4);
        }
        return;
    }

    // Phase 3 Isolation Guard Loop: Relational One-to-Many Render Triggers
    if (currentPhase === 'seeding' && data.player_seeds && editingPlayerIdx !== null) {
        const activeCharacter = data.player_seeds[editingPlayerIdx];
        if (activeCharacter.boxes) {
            activeCharacter.boxes.forEach((b, idx) => {
                const isCurrentlyActiveTarget = (idx === editingPlayerBoxIdx);
                const timeMatchesVideoHead = Math.abs(video.currentTime - b.timestamp) < 0.4;

                if (isCurrentlyActiveTarget || timeMatchesVideoHead) {
                    ctx.strokeStyle = isCurrentlyActiveTarget ? '#ff00ff' : (activeCharacter.team === 'light' ? '#28a745' : (activeCharacter.team === 'dark' ? '#dc3545' : '#ffc107'));
                    ctx.lineWidth = isCurrentlyActiveTarget ? 4 : 2;

                    const sx = toScreenX(b.x); const sy = toScreenY(b.y);
                    ctx.strokeRect(sx, sy, toScreenW(b.w), toScreenH(b.h));
                    ctx.fillStyle = ctx.strokeStyle; ctx.font = "bold 11px monospace";
                    ctx.fillText(`${activeCharacter.name} [Box #${idx + 1}]`, sx, sy - 4);
                }
            });
        }
    }

    // Phase 4 Isolation Guard Loop
    if (currentPhase === 'ball' && data.ball_samples) {
        data.ball_samples.forEach((b, idx) => {
            if (editingBallIdx !== null) {
                if (idx === editingBallIdx) {
                    ctx.strokeStyle = '#ff00ff'; ctx.lineWidth = 4;
                    ctx.strokeRect(toScreenX(b.box.x), toScreenY(b.box.y), toScreenW(b.box.w), toScreenH(b.box.h));
                }
            } else if (Math.abs(video.currentTime - b.timestamp) < 0.4) {
                ctx.strokeStyle = b.status === 'clear' ? '#28a745' : '#17a2b8';
                ctx.lineWidth = 2;
                ctx.strokeRect(toScreenX(b.box.x), toScreenY(b.box.y), toScreenW(b.box.w), toScreenH(b.box.h));
            }
        });
    }

    if (isDrawing) {
        ctx.strokeStyle = '#ffeb3b'; ctx.lineWidth = 2;
        ctx.strokeRect(dragStart.rawX, dragStart.rawY, (toScreenX(currentMouse.x)) - dragStart.rawX, (toScreenY(currentMouse.y)) - dragStart.rawY);
    }
}

function handleTextareaCursorSync() { return; }

// =====================================================================
// 💾 CONFIG SERVER COUPLING PERSISTENCE CONTROLLER
// =====================================================================
function saveCalibration() {
    fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => {
        if (res.ok) {
            alert('Calibration progress saved to disk successfully!');
        } else {
            alert('Server rejected the calibration payload configuration data.');
        }
    })
    .catch(err => {
        alert(`Critical Network Failure: Unable to reach the backend server.\nDetails: ${err.message}`);
    });
}