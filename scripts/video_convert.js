/**
 * Downframe video to 20fps and preserve resolution, audio and other properties
 * Usage: node video_convert.js input.mp4 output.mp4
 *
 * Uses ffmpeg stored in "/bin/ffmpeg.exe" to perform the conversion.
 */

const { exec, execSync } = require('child_process');
const path = require('path');

// Get command line arguments
const [,, inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node video_convert.js input.mp4 output.mp4');
  process.exit(1);
}

// Path to ffmpeg executable
const ffmpegPath = path.join(__dirname, '../bin', 'ffmpeg.exe');


/**
 * Detect if AMD GPU Hardware Encoding (AMF) is supported
 */
let useGpu = false;
try {
    // Run 'ffmpeg -encoders' and capture the text output
    const encodersOutput = execSync(`"${ffmpegPath}" -encoders`, { encoding: 'utf-8' });

    // 'h264_amf' is specific to AMD Radeon cards.
    // NVIDIA uses 'h264_nvenc' and Intel uses 'h264_qsv'.
    if (encodersOutput.includes('h264_amf')) {
        useGpu = true;
    }
} catch (error) {
    // Fallback to CPU if the ffmpeg command fails or isn't found
    console.warn("Could not check GPU encoders, defaulting to CPU processing.", error.message);
    useGpu = false;
}


// Cleaned up CPU fallback command (removed the stray hardware accelerator at the end)
const commandCpu = `"${ffmpegPath}" -i "${inputPath}" -vf "fps=20" -c:v libx264 -preset superfast -crf 22 -bf 0 -g 20 -an "${outputPath}"`;
// Optimized AMD AMF Hardware Accelerated command
const commandGpu = `"${ffmpegPath}" -hwaccel d3d11va -i "${inputPath}" -vf "fps=20" -c:v h264_amf -rc cqp -qp_i 22 -qp_p 22 -bf 0 -g 20 -an "${outputPath}"`;
exec(useGpu ? commandGpu : commandCpu, (error, stdout, stderr) => {
  if (error) {
    console.error(`Error converting video: ${error}`);
    process.exit(1);
  }
  console.log('Video converted successfully.');
});