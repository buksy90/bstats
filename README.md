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
Pull the raw match footage (`60fps`) from your source URL into the local directory.
```bash
npm run download -- <url> ./videos/raw_match.mp4
```

### 2. Encode and Optimize Video
Normalize the footage down to a strict 20fps constant frame rate. This optimizes the file structure for sequential frame decoding and drastically speeds up the machine learning inference phase.

```bash
npm run downframe -- ./videos/raw_match.mp4 ./videos/processed_match_20fps.mp4
```

### 3. Interactive Court Calibration (Manual User Input)
Before the AI processes the video, you will open a lightweight local web interface (calibrate.html) to quickly map out the parameters of the physical environment:
- Court Boundaries: Click the 4 physical corners of the basketball court (even outside the video borders if a corner is cut off). The system uses these points to project a bird's-eye view map of the playground.
- The Rims: Click and drag a 2D bounding box around the opening of both rims (Left and Right baskets).
- Basketball Sampling: Box a basketball across a pool of candidate frames to provide baseline dimensions and color context.

### 4. AI Batch Inference (Automated Background Processing)
Run the automated tracking core. Using your AMD GPU via DirectML, the script processes the video slice without user intervention to compile raw tracking data points and export a comprehensive tracking log.

```bash
# (one time) install Python's core computer vision and machine learning libraries
pip install ultralytics opencv-python numpy onnxruntime-directml tqdm
pip uninstall -y onnxruntime onnxruntime-directml
pip install onnxruntime-directml==1.24.4

# Execute the tracking core on your optimized video asset
python scripts/ai_tracker.py processed_match_20fps.mp4
```

### 5. Player & Team Labeling (Manual User Input)

Because players cross paths, sub out, or get blocked out of view, the AI's temporary tracking IDs will occasionally break. A clean local review screen allows you to resolve these ambiguities in minutes:

- **Assign Teams**: The AI automatically groups the players into two distinct clusters based on jersey colors. You simply toggle which cluster is "Team Light" and which is "Team Dark".
- **Map Player Identities**: The UI displays a grid of cropped player thumbnail outfits. You assign real names over the temporary track IDs (e.g., mapping track_id: 129 to "John").
- **Resolve Substitution Breaks**: Review flagged timeline segments where an ID brokenly vanished or swapped during a chaotic play to confirm continuity.

### 6. Stats Aggregation & LLM Commentary Generation
The system merges your verified player names with the raw spatial logs, calculating true distances run, court map charts, and possession percentages. This structured payload is then sent to your local Ollama instance, which compiles the final output into an engaging text timeline commentary and a detailed player performance box-score report.

## 🏀 Backend Architecture: Dual-Engine Core
To maximize real-time processing speeds on AMD hardware via DirectML while compensating for deep learning deficits regarding small, fast-moving objects, bstats utilizes a Dual-Engine Core architecture inside its tracking script.

While players are tracked via a convolutional neural network (YOLOv8 + ByteTrack), the basketball tracking uses a multi-layered, physics-driven heuristics engine.

              +-----------------------+
              |  Input Video Stream   |
              +-----------+-----------+
                          |
          +---------------+---------------+
          |                               |
          v                               v
+--------------------+           +--------------------+
|  Player Tracking   |           |   Ball Tracking    |
|   (YOLOv8 + Byte)  |           | (Custom Heuristics)|
+----------+---------+           +---------+----------+
           |                               |
           +---------------+---------------+
                           |
                           v
                +-----------------------+
                | Fusion Analytics Core |
                |  (Possession & Subs)  |
                +-----------------------+

### Player Analytics Core (Deep Learning)
Players are detected using YOLOv8 optimized via ONNX Runtime for DirectML to run natively on your Radeon RX 7800 XT, achieving over 40+ FPS. Temporal continuity is maintained frame-to-frame using the ByteTrack bounding-box matching engine.

### The Basketball Heuristic Arsenal (Computer Vision & Physics)
Because a fast-moving basketball is highly susceptible to motion blur and temporary player occlusions, standard deep learning object models easily lose track of it. bstats bypasses this limitation by running a concurrent, multi-layered heuristics tracking loop:

1. **Automated Background Modeling & Frame Differencing**: The script samples frames across the match video and extracts a mathematical median pixel map to generate a pristine image of the empty court. On every active frame, it computes an absolute pixel difference layer (|Current Frame - Background|). This instantly erases the court, hoop stands, and lines, isolating only moving entities.

2. **HSV Color Signature Gating**: Utilizing the user-verified OK Clear bounding boxes from calibration, the script isolates the precise hue distribution of your match ball under the specific gym lighting. It scans the moving-pixel layer specifically for these color blobs.

3. **Motion Vector & Proximity Gating**: A basketball obeys Newtonian physics and cannot teleport. The engine projects a localized "search bubble" around the ball’s last known position based on its active trajectory vector. Any color blobs found outside this boundary are discarded as environmental noise.

4. **Parabolic Arc Fitting (RANSAC Curves)**: Airborne passes and shot trajectories are validated against a quadratic regression model. Chaotic, jagged point paths are discarded, while points aligning with clean mathematical parabolas are confirmed as true ball flight paths.

### 🎯 Ball Handlers & Shot Detection Logic
- **Possession Tracking**: The engine monitors the proximity vector between the tracked ball coordinate and active player feet. If the ball is within a strict 1.5-meter radius and matches a player's relative speed vector, that specific player ID is credited with active possession.
- **Made Shot**: The ball's parabolic arc enters the top boundary of your calibrated rim box and exits out the bottom with a clean downward velocity vector.
- **Missed Shot / Rim Hit**: The ball intersects with your rim box coordinates, but its velocity vector instantly shifts upward or sharply sideways, signaling a physical bounce.
- **Airball**: The ball passes completely outside or underneath the calibrated rim coordinates without intersecting them, followed immediately by an out-of-bounds frame transition or a defensive possession change.

---

## 🚀 Future Roadmap: TrackNet Migration

If extreme crowd clutter, chaotic court reflections, or identical jersey colors limit the accuracy of the custom heuristics engine, the system is designed to transition to a **TrackNet Deep Temporal Heatmap** architecture.

### Retaining YOLO for Players, Swapping the Ball Engine
Under this planned upgrade, YOLOv8 + ByteTrack will remain completely untouched to handle high-performance player tracking and substitution mapping. TrackNet will be introduced strictly to replace the custom ball heuristics engine, transforming the script into a dual-neural-network pipeline.

+-----------------------------------------------------------------------+
|                         INPUT VIDEO STREAM                            |
+-----------------------------------┬-----------------------------------+
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
+-----------------------+                             +-----------------------+
|    PLAYER TRACKING    |                             |     BALL TRACKING     |
|   (YOLOv8 Engine)     |                             |   (TrackNet Engine)   |
|  Identifies Bounding  |                             | Generates Temporal    |
|   Boxes of Athletes   |                             | Coordinate Heatmaps   |
+--------┬--------------+                             +--------------┬--------+
         │                                                           │
         └──────────────────────────┬────────────────────────────────┘
                                    ▼
                        +-----------------------+
                        | FUSION ANALYTICS CORE |
                        +-----------------------+

### Expected Improvements with TrackNet:
- **Motion Blur Optimization**: TrackNet processes a sliding temporal stack of consecutive video frames simultaneously. Instead of viewing a fast pass as a broken smudge, it converts motion blur streaks into a critical trajectory asset, using the elongation to calculate exact ball vectors.
- **Resilience to Occlusion**: By evaluating preceding and succeeding frames in a single processing step, TrackNet can accurately predict and maintain tracking across frames where the ball is temporarily hidden behind a player's back, arm, or the rim layout.
- **Deterministic Precision**: Bypasses lighting variances and floor wood reflections that can throw off HSV color mapping, ensuring near-perfect tracking coverage during high-speed transitions and deep shot arcs.

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