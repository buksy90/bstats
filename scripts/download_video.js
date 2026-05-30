/**
 * Downloads a video from a given URL and saves it to the specified path.
 * Usage: node download_video.js <video_url> <save_path>
 * Example: node download_video.js https://example.com/video.mp4 ./video.mp4
 *
 * Uses yt-dlp stored in "/bin/yt-dlp.exe" to perform the download.
 */

const { exec } = require('child_process');
const path = require('path');

// Get command line arguments
const [,, videoUrl, savePath] = process.argv;
if (!videoUrl || !savePath) {
    console.error('Usage: node download_video.js <video_url> <save_path>');
    process.exit(1);
}

// Path to yt-dlp executable
const ytDlpPath = path.join(__dirname, '../bin', 'yt-dlp.exe');
// Construct the command to download the video
const command = `"${ytDlpPath}" -o "${savePath}" "${videoUrl}"  -f "bv*[height=1080][fps=60]+ba/b[height=1080]" --merge-output-format mp4`;
exec(command, (error, stdout, stderr) => {
    if (error) {
        console.error(`Error downloading video: ${error}`);
        process.exit(1);
    }
    console.log('Video downloaded successfully.');
});
