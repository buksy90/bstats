# This houses your multi-factor heuristic ball processing code. It pulls the coordinates of the
# manually verified basketball bounding boxes from calibration to generate a dedicated HSV tracking
# range mask, and applies motion vector constraints to screen out visual environment noise.

import cv2
import numpy as np
import os
from tqdm import tqdm

class HeuristicBallTracker:
    def __init__(self, calibration_data, video_fps):
        self.calibration = calibration_data
        self.fps = video_fps
        self.last_known_pos = None  # (m_x, m_y)
        self.movement_vector = (0.0, 0.0)

        # Extract lower/upper bounds strictly using CLEAR samples
        self.hsv_lower, self.hsv_upper = self._extract_clean_hsv_bounds()

        print(f"\n[Ball Engine] Initialized Filter Thresholds:")
        print(f" -> Pure Clear Lower HSV: {self.hsv_lower.tolist()}")
        print(f" -> Pure Clear Upper HSV: {self.hsv_upper.tolist()}")

    def _extract_clean_hsv_bounds(self):
        """Analyzes calibration metadata, completely ignoring covered boxes to avoid color pollution."""
        samples = self.calibration.get("ball_samples", [])

        # Default fallback parameters if no user configuration samples exist
        default_low = np.array([5, 45, 45], dtype=np.uint8)
        default_high = np.array([22, 245, 245], dtype=np.uint8)

        if not samples:
            return default_low, default_high

        h_vals, s_vals, v_vals = [], [], []

        for sample_entry in samples:
            # STRATEGY ENFORCEMENT: Ignore 'covered' entries completely for color masking
            if isinstance(sample_entry, dict) and sample_entry.get("status") == "clear":
                box = sample_entry.get("box", {})
                # Look for reference frame context mappings
                img_path = os.path.join("videos", "calibration_frame.jpg")

                if os.path.exists(img_path):
                    img = cv2.imread(img_path)
                    if img is not None:
                        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                        x, y, w, h = int(box['x']), int(box['y']), int(box['w']), int(box['h'])

                        # Inset crop down to 70% inner circle to eliminate border pixel bleed
                        cx, cy = x + w // 2, y + h // 2
                        nw, nh = int(w * 0.7), int(h * 0.7)
                        nx, ny = max(0, cx - nw // 2), max(0, cy - nh // 2)

                        crop = hsv[ny:min(hsv.shape[0], ny+nh), nx:min(hsv.shape[1], nx+nw)]
                        if crop.size > 0:
                            h_vals.extend(crop[:,:,0].flatten())
                            s_vals.extend(crop[:,:,1].flatten())
                            v_vals.extend(crop[:,:,2].flatten())

        if not h_vals:
            print("[Ball Engine] Warning: No 'clear' ball samples highlighted. Using default range.")
            return default_low, default_high

        # Extract limits and clamp to valid HSV array envelopes
        lower_bound = np.array([
            max(0, int(np.min(h_vals)) - 4),
            max(25, int(np.min(s_vals)) - 25),
            max(25, int(np.min(v_vals)) - 25)
        ], dtype=np.uint8)

        upper_bound = np.array([
            min(180, int(np.max(h_vals)) + 4),
            min(255, int(np.max(s_vals)) + 25),
            min(255, int(np.max(v_vals)) + 25)
        ], dtype=np.uint8)

        return lower_bound, upper_bound

    def track_ball_frame(self, frame, bg_gray, yolo_ball_box, get_court_meters_fn, frame_idx):
        """Processes live video slices to detect the ball via YOLO or custom color/movement fallbacks."""
        # Layer 1: Prioritize explicit deep learning YOLO boxes if available
        if yolo_ball_box is not None:
            bx1, by1, bx2, by2 = yolo_ball_box
            cx, cy = int((bx1 + bx2) / 2), int((by1 + by2) / 2)
            m_x, m_y = get_court_meters_fn(cx, cy)
            self._update_vector(m_x, m_y)
            return (cx, cy), (m_x, m_y)

        # Layer 2: Custom Computer Vision Fallback Loop
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, bg_gray)
        _, move_mask = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)

        # Intersect movement maps with our unpolluted color ranges
        combined = cv2.bitwise_and(color_mask, move_mask)
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_candidate = None
        min_vector_deviation = float('inf')

        for c in contours:
            area = cv2.contourArea(c)
            if area < 3 or area > 400:
                continue

            M = cv2.moments(c)
            if M["m00"] == 0: continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            m_x, m_y = get_court_meters_fn(cx, cy)

            # Ignore blobs manifesting outside live game boundary matrices
            if not (0 <= m_x <= 28 and 0 <= m_y <= 15):
                continue

            # Evaluate Newtonian vector tracking bubbles
            if self.last_known_pos is not None:
                pred_x = self.last_known_pos[0] + self.movement_vector[0]
                pred_y = self.last_known_pos[1] + self.movement_vector[1]
                distance_to_prediction = np.sqrt((m_x - pred_x)**2 + (m_y - pred_y)**2)

                # Reject impossible ball teleportations (max 4.2 meters per frame step window)
                if distance_to_prediction > 4.2:
                    continue

                if distance_to_prediction < min_vector_deviation:
                    min_vector_deviation = distance_to_prediction
                    best_candidate = ((cx, cy), (m_x, m_y))
            else:
                # Lock-on initial tracking point if context history is empty
                self._update_vector(m_x, m_y)
                return (cx, cy), (m_x, m_y)

        if best_candidate:
            self._update_vector(best_candidate[1][0], best_candidate[1][1])
            return best_candidate

        return None, None

    def _update_vector(self, next_x, next_y):
        if self.last_known_pos is not None:
            self.movement_vector = (next_x - self.last_known_pos[0], next_y - self.last_known_pos[1])
        self.last_known_pos = (next_x, next_y)