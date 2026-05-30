/**
 * Downframe video to 20fps and preserve resolution, audio and other properties
 * Usage: node video_convert.js input.mp4 output.mp4
 *
 * Uses ffmpeg stored in "/bin/ffmpeg.exe" to perform the conversion.
 */

const { exec } = require('child_process');
const path = require('path');

// Get command line arguments
const [,, inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node video_convert.js input.mp4 output.mp4');
  process.exit(1);
}

// Path to ffmpeg executable
const ffmpegPath = path.join(__dirname, '../bin', 'ffmpeg.exe');

// Construct the command to convert the video
const command = `"${ffmpegPath}" -i "${inputPath}" -r 20 -c:v copy -c:a copy "${outputPath}"`;
exec(command, (error, stdout, stderr) => {
  if (error) {
    console.error(`Error converting video: ${error}`);
    process.exit(1);
  }
  console.log('Video converted successfully.');
});