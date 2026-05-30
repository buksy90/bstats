# This houses your multi-factor heuristic ball processing code. It pulls the coordinates of the
# manually verified basketball bounding boxes from calibration to generate a dedicated HSV tracking
# range mask, and applies motion vector constraints to screen out visual environment noise.

import cv2
import numpy as np
import os

class HeuristicBallTracker:
    def __init__(self, calibration_data, video_fps):
        self.calibration = calibration_data
        self.fps = video_fps
        self.last_known_pos = None
        self.movement_vector = (0.0, 0.0)
        self.hsv_lower, self.hsv_upper = self._extract_hsv_bounds()

        print(f"\n[Ball Debug] Initialized Engine Metrics:")
        print(f" -> Lower HSV Tracking Net: {self.hsv_lower.tolist()}")
        print(f" -> Upper HSV Tracking Net: {self.hsv_upper.tolist()}")

    def _extract_hsv_bounds(self):
        samples = self.calibration.get("ball_samples", [])
        if not samples:
            return np.array([5, 50, 50], dtype=np.uint8), np.array([25, 255, 255], dtype=np.uint8)

        h_vals, s_vals, v_vals = [], [], []
        for s in samples:
            if isinstance(s, dict) and s.get("status") in ["clear", "covered"]:
                img_path = os.path.join("videos", f"ball_sample_{s['sample_frame']}.jpg")
                if os.path.exists(img_path):
                    img = cv2.imread(img_path)
                    if img is not None:
                        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                        x, y, w, h = int(s['x']), int(s['y']), int(s['w']), int(s['h'])
                        crop = hsv[y:y+h, x:x+w]
                        if crop.size > 0:
                            h_vals.extend(crop[:,:,0].flatten())
                            s_vals.extend(crop[:,:,1].flatten())
                            v_vals.extend(crop[:,:,2].flatten())

        if not h_vals:
            return np.array([5, 40, 40], dtype=np.uint8), np.array([22, 255, 255], dtype=np.uint8)

        lower_bound = np.array([
            max(0, int(np.min(h_vals)) - 6),
            max(20, int(np.min(s_vals)) - 35),
            max(20, int(np.min(v_vals)) - 35)
        ], dtype=np.uint8)

        upper_bound = np.array([
            min(180, int(np.max(h_vals)) + 6),
            min(255, int(np.max(s_vals)) + 35),
            min(255, int(np.max(v_vals)) + 35)
        ], dtype=np.uint8)

        return lower_bound, upper_bound

    def track_ball_frame(self, frame, bg_gray, yolo_ball_box, get_court_meters_fn, frame_idx):
        """Combines YOLO, Frame Differencing, and HSV Masks to isolate the ball."""
        # Preference 1: If YOLO successfully found a ball target, prioritize it
        if yolo_ball_box is not None:
            bx1, by1, bx2, by2 = yolo_ball_box
            cx, cy = int((bx1 + bx2) / 2), int((by1 + by2) / 2)
            m_x, m_y = get_court_meters_fn(cx, cy)
            self._update_vector(m_x, m_y)
            # Use tqdm.write so logs don't interrupt your progress bar layout cleanly
            from tqdm import tqdm
            tqdm.write(f"[Ball Debug] Frame {frame_idx}: YOLO confirmed tracking lock at pixel ({cx}, {cy}) -> meters ({m_x:.1f}, {m_y:.1f})")
            return (cx, cy), (m_x, m_y)

        # Preference 2: Heuristic Fallback Core (Differencing + Masking)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, bg_gray)
        _, move_mask = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)

        combined = cv2.bitwise_and(color_mask, move_mask)
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Print baseline diagnostic if pixels matched but didn't survive constraints
        from tqdm import tqdm
        if len(contours) > 0 and frame_idx % 20 == 0:
            tqdm.write(f"[Ball Debug] Frame {frame_idx}: Found {len(contours)} raw candidate color blobs moving on screen. Validating parameters...")

        best_candidate = None
        min_vector_deviation = float('inf')

        for idx, c in enumerate(contours):
            area = cv2.contourArea(c)
            # If area constraint discards blob, log the rejection criteria details
            if area < 3 or area > 450:
                if frame_idx % 40 == 0:
                    tqdm.write(f"  └─ Blob #{idx} Rejected: Area size mismatch ({area:.1f} pixels). Expected bounds 3-450.")
                continue

            M = cv2.moments(c)
            if M["m00"] == 0: continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            m_x, m_y = get_court_meters_fn(cx, cy)

            # Spatial boundary filter log check
            if not (0 <= m_x <= 28 and 0 <= m_y <= 15):
                if frame_idx % 40 == 0:
                    tqdm.write(f"  └─ Blob #{idx} Rejected: Coordinates fall outside flat court dimensions ({m_x:.1f}m, {m_y:.1f}m)")
                continue

            # Check Newtonian proximity tracking bubble limit constraints
            if self.last_known_pos is not None:
                predicted_x = self.last_known_pos[0] + self.movement_vector[0]
                predicted_y = self.last_known_pos[1] + self.movement_vector[1]
                distance_to_prediction = np.sqrt((m_x - predicted_x)**2 + (m_y - predicted_y)**2)

                if distance_to_prediction > 4.5:
                    if frame_idx % 40 == 0:
                        tqdm.write(f"  └─ Blob #{idx} Rejected: Failed Physics Velocity Vector (Moved {distance_to_prediction:.2f} meters since last frame, max is 4.5m).")
                    continue

                if distance_to_prediction < min_vector_deviation:
                    min_vector_deviation = distance_to_prediction
                    best_candidate = ((cx, cy), (m_x, m_y))
            else:
                # Establish initial tracking point lock-on
                tqdm.write(f"🎉 [Ball Debug] Frame {frame_idx}: Heuristics fallback found ball! Initializing tracking vector trajectory at ({m_x:.1f}m, {m_y:.1f}m)")
                self._update_vector(m_x, m_y)
                return (cx, cy), (m_x, m_y)

        if best_candidate:
            if frame_idx % 10 == 0:
                tqdm.write(f"🏀 [Ball Debug] Frame {frame_idx}: Tracking maintained via Custom Heuristics at ({best_candidate[1][0]:.1f}m, {best_candidate[1][1]:.1f}m)")
            self._update_vector(best_candidate[1][0], best_candidate[1][1])
            return best_candidate

        return None, None

    def _update_vector(self, next_x, next_y):
        if self.last_known_pos is not None:
            self.movement_vector = (next_x - self.last_known_pos[0], next_y - self.last_known_pos[1])
        self.last_known_pos = (next_x, next_y)