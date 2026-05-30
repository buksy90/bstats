# bstats (Basketball Analytics Engine)

`bstats` is a local, AI-powered sports analytics tool designed to process amateur basketball footage recorded from a static camera. It automates tracking match events—including **shots made/missed, rebounds, steals, turnovers, and passes**—and attributes them to specific players and teams along a chronological timeline.

The project utilizes a hybrid pipeline: a fast **Node.js** workflow engine for data orchestration and asset management, paired with an upcoming local **Python + YOLO** computer vision pipeline optimized for AMD Radeon GPUs (DirectML).

---

## 🚀 Features & Roadmap

- [x] **Video Downloader**: Integrated `yt-dlp` handler to download match videos from web URLs.
- [x] **Video Preprocessor**: Hardware-accelerated `ffmpeg` script to normalize video to a constant **20 FPS**, making it ideal for local AI computer vision processing.
- [ ] **AI Tracking Engine** *(In Progress)*: YOLO-based detection of players and the basketball, using color histograms to isolate teams (Light vs. Dark shirts).
- [ ] **Event Logging Engine** *(Planned)*: Automated tracking of match metrics with high-resolution metadata:
  - **Timestamp / Game Time**
  - **Team Attribution** (Team Light vs. Team Dark)
  - **Player Resolution** (Dynamic tracking ID linked to real player names via user verification)
  - **Action Types**: Shot Made, Shot Missed, Rebound, Steal, Turnover, and Pass.

---

## 🔄 Pipeline Workflow & Order of Operations

To achieve high-accuracy statistics from an amateur, single-camera setup, `bstats` relies on a semi-automated pipeline. This combines raw AI computing power with quick, strategic human inputs to resolve real-world ambiguities (like player substitutions and visual occlusions).

[1. Download Video] ──> [2. Encode to 20fps] ──> [3. Interactive Court Calibration]
[4. AI Batch Inference] ──> [5. Player & Team Labeling] ──> [6. Final Stats & LLM Report]

### 1. Download Video
Pull the raw match footage (`60fps`) from your source URL into the local `/download` directory.
```bash
npm run download -- <url> ./videos/raw_match.mp4
```

### 2. Encode and Optimize Video
Normalize the footage down to a strict 20fps constant frame rate. This optimizes the file structure for sequential frame decoding and drastically speeds up the machine learning inference phase.

```bash
npm run downframe -- ./videos/raw_match.mp4 ./videos/processed_match_20fps.mp4
```

### 3. Interactive Court Calibration (Manual User Input)
Before the AI processes the video, you will open a lightweight local HTML/TypeScript interface. The app will render the first frame of the video, allowing you to use your mouse to map the physics environment:
- Court Boundaries: You will click the 4 physical corners of the basketball court. The system uses these 4 coordinate points to execute a Homography Matrix (Perspective Transformation). This mathematically translates the skewed camera view into a flat, 28m x 15m bird's-eye view grid used to calculate player running distances.
- The Baskets: You will click and drag a 2D bounding box (rectangle) around the opening of both rims (Left Basket and Right Basket).

#### How AI Detects Made vs. Missed Shots:
Once you define the exact rectangular zone of the rim, the backend tracks the mathematical trajectory arc of the ball:
- Made Shot: The ball enters the top of your calibrated rim box and exits out the bottom with a downward velocity vector.
- Missed Shot / Rim Hit: The ball's parabolic arc intersects with the rim box coordinates, but its velocity vector instantly shifts upward or sharply sideways (signaling a bounce off the rim or backboard).
- Airball: The ball passes completely outside or underneath the calibrated rim coordinates without intersecting them, followed immediately by a player possession change or out-of-bounds event.

### 4. AI Batch Inference (Automated Background Processing)
The Python backend script runs without user intervention. Using your AMD GPU via DirectML, it scans the video to log raw tracking points:
- Tracks the bounding boxes of all moving bodies, assigning temporary IDs (e.g., ID_01, ID_02).
- Extracts color histograms (unique outfit clothing profiles) for every detected body.
- Logs the exact coordinate path of the basketball.
- Flags automated events (e.g., ball entering a rim zone, sudden change of ball vector between different player IDs indicating a pass, steal, or turnover).

```bash
# (one time) install Python's core computer vision and machine learning libraries
pip install ultralytics opencv-python numpy onnxruntime-directml

python scripts/ai_tracker.py
```


### 5. Player & Team Labeling (Manual User Input)
Because players cross paths, sub out, or get blocked out of view by other players, the AI's temporary tracking IDs will occasionally break. The local web UI will present a clean review screen to resolve this:
- Assign Teams: The AI will automatically group the players into two distinct clusters using the color histograms of their shirts (separating light shirts from dark shirts). You simply toggle which cluster is "Team Light" and which is "Team Dark".
- Name the Outfits: The UI displays a grid of cropped thumbnail images showing the distinct outfits detected during the game. You type real names over the temporary IDs (e.g., mapping ID_03 [Red shirt / Blue shorts] to "John", and mapping ID_14 [Green shirt / White shorts] to "Dave").
- Resolve Conflicts: If a substitution occurred or an ID swap happened during a chaotic play, the timeline will show a flagged warning. The UI will let you jump to that exact 5-second video clip and verify: "Who grabbed this rebound?" with a single click.

### 6. Stats Aggregation & LLM Commentary Generation
The system merges the verified player names with the raw spatial-temporal logs. It calculates total distances run (filtering out benched players outside the court boundaries), counts box-score metrics, and fires the structured JSON payload to your local Ollama instance.

Ollama compiles the final output into an engaging text timeline and fully detailed player performance report.

## 📂 Project Structure

```text
bstats/
├── bin/
│   ├── ffmpeg.exe          # FFmpeg executable for video encoding
│   └── yt-dlp.exe          # YouTube-DL interface for asset fetching
├── videos/                 # Target directory for raw downloaded videos
├── scripts/
│   ├── download_video.js   # Script wrapper for video fetching
│   └── video_convert.js    # Script wrapper for 20 FPS video processing
├── .gitignore
├── package.json
└── README.md