/**
 * Downframe video to 20fps and preserve resolution, audio and other properties
 * Usage: node video_convert.js input.mp4 output.mp4
 *
 * Uses ffmpeg stored in "/bin/ffmpeg.exe" to perform the conversion.
 */

const { spawn, execSync } = require('child_process');
const path = require('path');

// Get command line arguments
const [,, inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node video_convert.js input.mp4 output.mp4');
  process.exit(1);
}

const ffmpegPath = path.join(__dirname, "../bin/ffmpeg.exe");
const ffprobePath = path.join(__dirname, "../bin/ffprobe.exe");

function getDurationSeconds(file) {
    const result = execSync(
        `"${ffprobePath}" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${file}"`,
        { encoding: "utf8" }
    );

    return parseFloat(result.trim());
}

function hasAmfEncoder() {
    try {
        const encoders = execSync(
            `"${ffmpegPath}" -hide_banner -encoders`,
            { encoding: "utf8" }
        );

        // 'h264_amf' is specific to AMD Radeon cards.
        // NVIDIA uses 'h264_nvenc' and Intel uses 'h264_qsv'.
        if (encoders.includes("h264_amf")) {
          console.log("");
          console.log("AMF hardware encoder detected. Using GPU acceleration for video conversion.");
          return true;
        }
        return false;
    } catch (error) {
        console.warn("Could not check GPU encoders, defaulting to CPU processing.", error.message);
        return false;
    }
}

const totalDuration = getDurationSeconds(inputPath);
const useGpu = hasAmfEncoder();


const argsShared = [
    "-hide_banner",

    "-hwaccel",
    "d3d11va",

    "-i",
    inputPath,

    "-vf",
    "fps=20",

    "-bf",
    "0",

    "-g",
    "20",

    "-an",

    "-progress",
    "pipe:1",

    "-nostats",

    "-y",
];
const argsGpu = [
    "-c:v",
    "h264_amf",

    "-usage",
    "transcoding",

    "-quality",
    "speed",

    "-rc",
    "cqp",

    "-qp_i",
    "22",

    "-qp_p",
    "22",

    "-async_depth",
    "32",

    "-smart_access_video",
    "1",

    "-fps_mode",
    "passthrough",

    outputPath,
];

const argsCpu = [
    "-c:v",
    "libx264",

    "-preset",
    "superfast",

    "-crf",
    "22",

    outputPath,
];

let progressBuffer = "";

const ffmpeg = spawn(
    ffmpegPath,
    [
        ...argsShared,
        ...(useGpu ? argsGpu : argsCpu),
    ],
    {
        windowsHide: true,
    }
);

ffmpeg.stdout.setEncoding("utf8");
ffmpeg.stdout.on("data", chunk => {
    progressBuffer += chunk;

    const lines = progressBuffer.split(/\r?\n/);
    progressBuffer = lines.pop() || "";

    let outTimeMs;
    let speed;

    for (const line of lines) {
        if (line.startsWith("out_time_ms=")) {
            outTimeMs = Number(line.substring(12));
        }

        if (line.startsWith("speed=")) {
            speed = line.substring(6);
        }
    }

    if (outTimeMs) {
        const processedSeconds = outTimeMs / 1_000_000;
        const percent = (processedSeconds / totalDuration) * 100;
        let eta = "--";

        if (speed) {
            const speedNum = parseFloat(speed.replace("x", ""));
            if (!Number.isNaN(speedNum) && speedNum > 0) {
                const remaining = (totalDuration - processedSeconds) / speedNum;
                eta = Math.round(remaining / 60) + "m";
            }
        }

        process.stdout.write(`\r${percent.toFixed(1)}%  ${speed || ""}  ETA ${eta}`);
    }
});

ffmpeg.stderr.on("data", chunk => {
    const text = chunk.toString();

    if (text.includes("Error") || text.includes("error")) {
        console.error(text);
    }
});

ffmpeg.on("close", code => {
    console.log("");

    if (code === 0) {
        console.log("Video converted successfully.");
    } else {
        console.error(`FFmpeg exited with code ${code}`);
        process.exit(code);
    }
});