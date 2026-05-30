const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec, execSync } = require('child_process');

const [,, videoFilename] = process.argv;
if (!videoFilename) {
    console.error('Usage: node calibrate.js <video_filename>');
    process.exit(1);
}


// Paths (aligned with your project structure)
const ffmpegPath = path.join(__dirname, '../bin/ffmpeg.exe');
const inputVideo = path.join(__dirname, '..', videoFilename);
const frameImg = path.join(__dirname, '../videos/calibration_frame.jpg');
const jsonOutput = path.join(__dirname, '../videos/calibration.json');

const PORT = 8080;

/**
 * Step 1: Extract a static frame from the video using FFmpeg if it doesn't exist
 */
if (!fs.existsSync(frameImg)) {
    console.log("[Calibrate] Extracting calibration frame from video...");
    try {
        // Extracts 1 frame at the 2-second mark to avoid any initial camera shake/black screens
        execSync(`"${ffmpegPath}" -y -ss 00:00:02 -i "${inputVideo}" -vframes 1 "${frameImg}"`);
        console.log("[Calibrate] Frame extracted successfully.");
    } catch (err) {
        console.error("[Calibrate] Failed to extract frame. Make sure step 2 video exists.", err.message);
        process.exit(1);
    }
}

/**
 * Step 2: The Interactive Frontend Interface (HTML/JS)
 */
const htmlContent = fs.readFileSync(path.join(__dirname, 'calibrate.html'), 'utf8');

/**
 * Step 3: Run the local HTTP Server
 */
const server = http.createServer((req, res) => {
    if (req.url === '/' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(htmlContent);
    }
    else if (req.url === '/frame.jpg' && req.method === 'GET') {
        fs.readFile(frameImg, (err, content) => {
            if (err) {
                res.writeHead(404);
                res.end("Image not found");
            } else {
                res.writeHead(200, { 'Content-Type': 'image/jpeg' });
                res.end(content);
            }
        });
    }
    else if (req.url === '/api/save' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => { body += chunk.toString(); });
        req.on('end', () => {
            fs.writeFileSync(jsonOutput, body, 'utf8');
            console.log(`\n[Calibrate] Calibration configuration saved to: ${jsonOutput}`);
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ status: 'success' }));

            // Clean shutdown of the server once task is complete
            server.close(() => {
                console.log("[Calibrate] Server stopped safely.");
                process.exit(0);
            });
        });
    }
});

server.listen(PORT, () => {
    console.log(`[Calibrate] Server running at http://localhost:${PORT}`);
    console.log("[Calibrate] Automatically launching your web browser...");
    // Native Windows command to auto-open default browser
    exec(`start http://localhost:${PORT}`);
});