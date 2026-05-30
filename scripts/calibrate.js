const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec, execSync } = require('child_process');
const url = require('url');

// =====================================================================
// ⚙️ CALIBRATION SAMPLING CONFIGURATION
// =====================================================================
const TOTAL_BALL_SAMPLES_POOL = 25;
const REQUIRED_BALL_SAMPLES = 7;
// =====================================================================

const ffmpegPath = path.join(__dirname, '../bin/ffmpeg.exe');
const targetVideoName = process.argv[2] || "processed_match_20fps.mp4";
const actualVideoPath = path.join(__dirname, '../videos', targetVideoName);
const jsonOutput = path.join(__dirname, '../videos', 'calibration.json');
const frameImg = path.join(__dirname, '../videos/calibration_frame.jpg');

const PORT = 8080;

if (!fs.existsSync(actualVideoPath)) {
    print(`Error: Target video asset missing at ${actualVideoPath}`);
    process.exit(1);
}

let durationSeconds = 60;
try {
    const ffprobePath = path.join(__dirname, '../bin/ffprobe.exe');
    const meta = execSync(`"${ffprobePath}" -v error -show_entries format=duration -of default=noprint_wrappers=1:nocorner=1 "${actualVideoPath}"`, { encoding: 'utf-8' });
    if (parseFloat(meta)) durationSeconds = parseFloat(meta);
} catch (e) {}

if (!fs.existsSync(frameImg)) {
    execSync(`"${ffmpegPath}" -y -ss 00:00:02 -i "${actualVideoPath}" -vframes 1 "${frameImg}"`);
}

const sampleTimes = [];
const startPercentage = 0.05;
const endPercentage = 0.95;
const step = (endPercentage - startPercentage) / (TOTAL_BALL_SAMPLES_POOL - 1);

for (let i = 0; i < TOTAL_BALL_SAMPLES_POOL; i++) {
    sampleTimes.push(durationSeconds * (startPercentage + (step * i)));
}

sampleTimes.forEach((seconds, idx) => {
    const outImg = path.join(__dirname, `../videos/ball_sample_${idx + 1}.jpg`);
    if (!fs.existsSync(outImg)) {
        const timestamp = new Date(seconds * 1000).toISOString().substr(11, 8);
        execSync(`"${ffmpegPath}" -y -ss ${timestamp} -i "${actualVideoPath}" -vframes 1 "${outImg}"`);
    }
});

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);

    if (parsedUrl.pathname === '/' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(fs.readFileSync(path.join(__dirname, 'calibrate.html'), 'utf8'));
    }
    else if (parsedUrl.pathname === '/frame.jpg' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'image/jpeg' });
        res.end(fs.readFileSync(frameImg));
    }
    else if (parsedUrl.pathname === '/api/config' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ required_samples: REQUIRED_BALL_SAMPLES, pool_size: TOTAL_BALL_SAMPLES_POOL }));
    }
    // 🔥 NEW: On-Demand Dynamic Frame Generation Engine
    else if (parsedUrl.pathname === '/api/request_frame' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const payload = JSON.parse(body);
                const userTime = payload.time; // Format: MM:SS.m

                // Parse timestamp format safely into hours:minutes:seconds.ms
                const parts = userTime.split(':');
                let minutes = parseInt(parts[0], 10) || 0;
                let secondsStr = parts[1] || '0';

                let minStr = String(minutes).padStart(2, '0');
                // Format directly into standard ffmpeg target time strings
                const ffmpegTimestamp = `00:${minStr}:${secondsStr.padStart(4, '0')}`;

                const customIndex = String(payload.index);
                const outPath = path.join(__dirname, `../videos/ball_sample_${customIndex}.jpg`);

                // Trigger dynamic extraction command block
                execSync(`"${ffmpegPath}" -y -ss ${ffmpegTimestamp} -i "${actualVideoPath}" -vframes 1 "${outPath}"`);

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'success', path: `/ball_sample_${customIndex}.jpg?t=${Date.now()}` }));
            } catch (err) {
                res.writeHead(500); res.end(JSON.stringify({ error: err.message }));
            }
        });
    }
    else if (parsedUrl.pathname.startsWith('/ball_sample_') && req.method === 'GET') {
        const imgName = parsedUrl.pathname.substring(1);
        const samplePath = path.join(__dirname, '../videos', imgName);
        if (fs.existsSync(samplePath)) {
            res.writeHead(200, { 'Content-Type': 'image/jpeg' });
            res.end(fs.readFileSync(samplePath));
        } else {
            res.writeHead(404); res.end();
        }
    }
    else if (parsedUrl.pathname === '/api/save' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            fs.writeFileSync(jsonOutput, body, 'utf8');
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ status: 'success' }));
            server.close(() => { process.exit(0); });
        });
    }
});

server.listen(PORT, () => {
    console.log(`[Calibrate] Server running at http://localhost:${PORT}`);
    exec(`start http://localhost:${PORT}`);
});