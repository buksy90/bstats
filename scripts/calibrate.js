const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec, execSync } = require('child_process');
const url = require('url');

// =====================================================================
// ⚙️ CALIBRATION SAMPLING CONFIGURATION
// =====================================================================
const REQUIRED_BALL_SAMPLES = 5;
const TOTAL_BALL_SAMPLES_POOL = 10;
const PORT = 8080;
// =====================================================================

const ffmpegPath = path.join(__dirname, '../bin/ffmpeg.exe');
const ffprobePath = path.join(__dirname, '../bin/ffprobe.exe');
const targetVideoName = process.argv[2] || "processed_match_20fps.mp4";
const actualVideoPath = path.join(__dirname, '../videos', targetVideoName);
const jsonOutput = path.join(__dirname, '../videos', 'calibration.json');
const frameImg = path.join(__dirname, '../videos/calibration_frame.jpg');

if (!fs.existsSync(actualVideoPath)) {
    console.error(`Error: Video missing at target path: ${actualVideoPath}`);
    process.exit(1);
}

if (!fs.existsSync(path.dirname(frameImg))) {
    fs.mkdirSync(path.dirname(frameImg), { recursive: true });
}

// 📊 METADATA EXTRACTION ENGINE (Cached on Startup)
let videoMetadataCache = {
    filename: targetVideoName,
    width: 1920,
    height: 1080,
    duration_seconds: 60.0,
    fps: 20.0,
    total_estimated_frames: 1200
};

try {
    console.log("[Server] Inspecting source stream characteristics via FFprobe...");
    const ffprobeRawOutput = execSync(
        `"${ffprobePath}" -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -show_entries format=duration -of json "${actualVideoPath}"`,
        { encoding: 'utf-8' }
    );

    const parsedProbe = JSON.parse(ffprobeRawOutput);

    if (parsedProbe.streams && parsedProbe.streams[0]) {
        const stream = parsedProbe.streams[0];
        videoMetadataCache.width = parseInt(stream.width, 10) || 1920;
        videoMetadataCache.height = parseInt(stream.height, 10) || 1080;

        if (stream.r_frame_rate) {
            const parts = stream.r_frame_rate.split('/');
            if (parts.length === 2 && parseFloat(parts[1]) !== 0) {
                videoMetadataCache.fps = Math.round((parseFloat(parts[0]) / parseFloat(parts[1])) * 100) / 100;
            }
        }
    }

    if (parsedProbe.format && parsedProbe.format.duration) {
        videoMetadataCache.duration_seconds = parseFloat(parsedProbe.format.duration);
    }

    videoMetadataCache.total_estimated_frames = Math.round(videoMetadataCache.duration_seconds * videoMetadataCache.fps);

    console.log(`[Server] Video Signature Identified: ${videoMetadataCache.width}x${videoMetadataCache.height} @ ${videoMetadataCache.fps} FPS`);

} catch (err) {
    console.warn("[Server] Warning: Failed to parse native metadata profiles. Falling back to defaults.", err.message);
}

if (!fs.existsSync(frameImg)) {
    try {
        execSync(`"${ffmpegPath}" -y -ss 00:00:02 -i "${actualVideoPath}" -vframes 1 "${frameImg}"`);
    } catch (e) {
        console.log("[Server] Base frame rendering skipped or failed initialization.");
    }
}

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);

    // 1. Dashboard View Route
    if (parsedUrl.pathname === '/' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(fs.readFileSync(path.join(__dirname, 'calibrate.html'), 'utf8'));
    }

    // 2. 🔥 NEW: Static Asset JavaScript Router Engine
    // Looks for any requested .js files sitting inside your scripts directory on disk
    // TODO: Update to support nested directories
    else if (parsedUrl.pathname.endsWith('.js') && req.method === 'GET') {
        const jsFilePath = path.join(__dirname, parsedUrl.pathname);

        if (fs.existsSync(jsFilePath)) {
            res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8' });
            res.end(fs.readFileSync(jsFilePath, 'utf8'));
        } else {
            console.log(404, JSON.stringify({ event: 'js_request', pathName: parsedUrl.pathname, resolvedPath: jsFilePath  }));
            res.writeHead(404); res.end();
        }
    }

    // 3. HTTP Byte-Range Stream Router
    else if (parsedUrl.pathname === '/video_stream.mp4' && req.method === 'GET') {
        if (!fs.existsSync(actualVideoPath)) {
            res.writeHead(404); return res.end();
        }

        const stat = fs.statSync(actualVideoPath);
        const fileSize = stat.size;
        const range = req.headers.range;

        if (range) {
            const parts = range.replace(/bytes=/, "").split("-");
            const start = parseInt(parts[0], 10);
            const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;

            if (start >= fileSize || end >= fileSize) {
                res.writeHead(416, { 'Content-Range': `bytes */${fileSize}` });
                return res.end();
            }

            const chunksize = (end - start) + 1;
            const file = fs.createReadStream(actualVideoPath, { start, end });

            res.writeHead(206, {
                'Content-Range': `bytes ${start}-${end}/${fileSize}`,
                'Accept-Ranges': 'bytes',
                'Content-Length': chunksize,
                'Content-Type': 'video/mp4',
            });
            file.pipe(res);
        } else {
            res.writeHead(200, {
                'Content-Length': fileSize,
                'Content-Type': 'video/mp4',
            });
            fs.createReadStream(actualVideoPath).pipe(res);
        }
    }

    // 4. Static Calibration Frame Reference Route
    else if (parsedUrl.pathname === '/frame.jpg' && req.method === 'GET') {
        if (fs.existsSync(frameImg)) {
            res.writeHead(200, { 'Content-Type': 'image/jpeg' });
            res.end(fs.readFileSync(frameImg));
        } else {
            res.writeHead(404); res.end();
        }
    }

    // 5. API Configuration Synchronization Route
    else if (parsedUrl.pathname === '/api/config' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ required_samples: REQUIRED_BALL_SAMPLES, pool_size: TOTAL_BALL_SAMPLES_POOL }));
    }

    // 6. Video Characteristics Stream Endpoint
    else if (parsedUrl.pathname === '/api/video_meta' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(videoMetadataCache));
    }

    // 7. Dynamic Frame Request Extractor
    else if (parsedUrl.pathname === '/api/request_frame' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                const payload = JSON.parse(body);
                const userTime = payload.time;

                const parts = userTime.split(':');
                let minutes = parseInt(parts[0], 10) || 0;
                let secondsStr = parts[1] || '0';

                let minStr = String(minutes).padStart(2, '0');
                const ffmpegTimestamp = `00:${minStr}:${secondsStr.padStart(4, '0')}`;

                const customIndex = String(payload.index);
                const outPath = path.join(__dirname, `../videos/ball_sample_${customIndex}.jpg`);

                execSync(`"${ffmpegPath}" -y -ss ${ffmpegTimestamp} -i "${actualVideoPath}" -vframes 1 "${outPath}"`);

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'success', path: `/ball_sample_${customIndex}.jpg?t=${Date.now()}` }));
            } catch (err) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: err.message }));
            }
        });
    }

    // 8. Dynamic Ball Sample Asset Server
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

    // 9. Config Payload Update/Save Route
    else if (parsedUrl.pathname === '/api/save' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            try {
                fs.writeFileSync(jsonOutput, body, 'utf8');
                console.log(`\n[Server] Calibration intermediate states synchronized to: ${jsonOutput}`);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'success' }));
            } catch (err) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: err.message }));
            }
        });
    }

    else {
        res.writeHead(404); res.end();
    }
});

server.listen(PORT, () => {
    console.log(`[Calibrate] Streaming dashboard active at http://localhost:${PORT}`);
    exec(`start http://localhost:${PORT}`);
});