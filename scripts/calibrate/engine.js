// =====================================================================
// 🌍 GLOBAL STATE WORKSPACE MATRIX
// =====================================================================
let currentPhase = 'boundaries';
let data = {
    court_corners: [],
    substitution_zone: [],
    near_basket: null,
    far_basket: null,
    player_seeds: [], // Schema: [{ name, team, boxes: [{x,y,w,h,timestamp}] }]
    ball_samples: []
};

let isDrawing = false;
let dragStart = { x: 0, y: 0, rawX: 0, rawY: 0 };
let currentMouse = { x: 0, y: 0 };

let editingBallIdx = null;
let editingPlayerIdx = null;    // Tracks the active parent Character index
let editingPlayerBoxIdx = null; // Tracks the active visible Box sub-index for that Character

const LOCAL_STORAGE_KEY = "bstats_active_calibration_cache";
let viewGeom = { offsetX: 0, offsetY: 0, dispW: 0, dispH: 0, nativeW: 1920, nativeH: 1080 };

// =====================================================================
// 🛠️ DATA ENGINE & SYNCHRONIZATION UTILITIES
// =====================================================================
function resetDataStructure() {
    data = { court_corners: [], substitution_zone: [], near_basket: null, far_basket: null, player_seeds: [], ball_samples: [] };
    editingBallIdx = null;
    editingPlayerIdx = null;
    editingPlayerBoxIdx = null;
}

function updateTextarea() {
    const jsonEditor = document.getElementById('jsonEditor');
    if (jsonEditor) {
        jsonEditor.value = JSON.stringify(data, null, 2);
    }
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(data));

    // Refresh input lists across active sub-menus
    populateBallDropdown();
    populatePlayerDropdown();
    renderIdentityList();
}

function syncFromJson() {
    const jsonEditor = document.getElementById('jsonEditor');
    if (!jsonEditor) return;
    try {
        const parsed = JSON.parse(jsonEditor.value);
        data = parsed;
        localStorage.setItem(LOCAL_STORAGE_KEY, jsonEditor.value);

        if (data.near_basket && data.near_basket.attacked_by) {
            document.getElementById('selNearAttackedBy').value = data.near_basket.attacked_by;
        }
        if (data.far_basket && data.far_basket.attacked_by) {
            document.getElementById('selFarAttackedBy').value = data.far_basket.attacked_by;
        }

        populateBallDropdown();
        populatePlayerDropdown();
        renderIdentityList();
        recomputeGlobalHsv();

        if (typeof draw === 'function') draw();
    } catch(e) {
        // Quietly absorb parsing artifacts during active typing sequences
    }
}

// =====================================================================
// 📐 RESPONSIVE GEOMETRY & COORDINATE CONVERTERS
// =====================================================================
function getRelativeImageCoords(e) {
    const canvas = document.getElementById('overlayCanvas');
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const normX = Math.round((mouseX / viewGeom.dispW) * viewGeom.nativeW);
    const normY = Math.round((mouseY / viewGeom.dispH) * viewGeom.nativeH);
    return { x: normX, y: normY, rawX: mouseX, rawY: mouseY };
}

function toScreenX(nativeX) { return (nativeX / viewGeom.nativeW) * viewGeom.dispW; }
function toScreenY(nativeY) { return (nativeY / viewGeom.nativeH) * viewGeom.dispH; }
function toScreenW(nativeW) { return (nativeW / viewGeom.nativeW) * viewGeom.dispW; }
function toScreenH(nativeH) { return (nativeH / viewGeom.nativeH) * viewGeom.dispH; }

function formatTime(seconds) {
    let m = Math.floor(seconds / 60);
    let s = Math.floor(seconds % 60);
    let ms = Math.floor((seconds % 1) * 10);
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${ms}`;
}

// =====================================================================
// 📋 DYNAMIC DROPDOWN MENU GENERATION
// =====================================================================
function populateBallDropdown() {
    const sel = document.getElementById('selBallSample');
    if (!sel) return;
    sel.innerHTML = "";
    if (!data.ball_samples || data.ball_samples.length === 0) {
        sel.appendChild(new Option("-- No Samples Available --", ""));
        return;
    }
    data.ball_samples.forEach((b, idx) => {
        const title = `Sample #${idx + 1} (${b.status}) [${b.timestamp.toFixed(1)}s]`;
        const opt = new Option(title, idx);
        if (idx === editingBallIdx) opt.selected = true;
        sel.appendChild(opt);
    });
}

function populatePlayerDropdown() {
    const sel = document.getElementById('selPlayerSeed');
    if (!sel) return;
    sel.innerHTML = "";
    if (!data.player_seeds || data.player_seeds.length === 0) {
        sel.appendChild(new Option("-- No Characters Registered --", ""));
        return;
    }
    data.player_seeds.forEach((p, idx) => {
        const count = p.boxes ? p.boxes.length : 0;
        const title = `${p.name} (${p.team}) [${count} sample${count !== 1 ? 's' : ''}]`;
        const opt = new Option(title, idx);
        if (idx === editingPlayerIdx) opt.selected = true;
        sel.appendChild(opt);
    });
}

// =====================================================================
// 👥 RELATIONAL SUB-SAMPLE BOX ITERATOR LIST
// =====================================================================
function renderIdentityList() {
    const container = document.getElementById('seedingRegistryList');
    if (!container) return;
    container.innerHTML = "";

    if (editingPlayerIdx === null || !data.player_seeds[editingPlayerIdx]) {
        container.innerHTML = `<div style="color: #666; font-style: italic; padding: 4px;">Choose or create a profile above to list samples...</div>`;
        return;
    }

    const activeCharacter = data.player_seeds[editingPlayerIdx];
    if (!activeCharacter.boxes || activeCharacter.boxes.length === 0) {
        container.innerHTML = `<div style="color: #888; font-style: italic; padding: 4px;">No boxes drawn. Click and drag on video viewport area to attach samples.</div>`;
        return;
    }

    // Step through the specific boxes array owned by the currently selected profile
    activeCharacter.boxes.forEach((box, idx) => {
        const item = document.createElement('div');
        const isCurrentlyViewed = (idx === editingPlayerBoxIdx);

        item.className = `seeding-item team-${activeCharacter.team} ${isCurrentlyViewed ? 'active-sample' : ''}`;
        item.innerHTML = `
            <span onclick="handlePlayerBoxSelect(${idx})" style="flex: 1; padding: 4px 0;">
                Box #${idx + 1} &rarr; Timestamp: ${box.timestamp.toFixed(1)}s
            </span>
            <button class="delete-box-btn" onclick="deletePlayerBoxIndex(${idx}); event.stopPropagation();" title="Remove individual box step">&times;</button>
        `;
        container.appendChild(item);
    });
}

function recomputeGlobalHsv() {
    if (!data.ball_samples) return;
    let clearBalls = data.ball_samples.filter(b => b.status === 'clear');
    const lblLower = document.getElementById('lblLower');
    const lblUpper = document.getElementById('lblUpper');
    const swatchLower = document.getElementById('swatchLower');
    const swatchUpper = document.getElementById('swatchUpper');

    if (!lblLower) return;

    if (clearBalls.length === 0) {
        lblLower.textContent = "N/A"; lblUpper.textContent = "N/A";
        swatchLower.style.backgroundColor = "#333"; swatchUpper.style.backgroundColor = "#333";
        return;
    }

    lblLower.textContent = "[8, 45, 45]";
    lblUpper.textContent = "[18, 240, 240]";
    swatchLower.style.backgroundColor = "rgb(120, 60, 20)";
    swatchUpper.style.backgroundColor = "rgb(230, 130, 45)";
}