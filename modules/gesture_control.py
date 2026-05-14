"""
Hand gesture recognition module for Hermes Voice Assistant.
Uses MediaPipe Hands for local, real-time gesture detection.
"""

import logging
import math
import threading
import time
from collections import deque

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger(__name__)

# MediaPipe hand landmark indices
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# Finger tip/pip pairs for extension check (excluding thumb)
FINGER_TIPS = [INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP]
FINGER_PIPS = [INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP]

DEBOUNCE_SECONDS = 0.5
SWIPE_THRESHOLD = 0.12
SWIPE_HISTORY_SIZE = 5
PINCH_THRESHOLD = 0.05
TARGET_FPS = 15


class GestureController:
    """Detects hand gestures via webcam using MediaPipe Hands."""

    def __init__(self, on_gesture_callback=None):
        """
        Args:
            on_gesture_callback: callable receiving dict with keys
                'gesture' (str), 'confidence' (float), 'hand' ('left'|'right')
        """
        self.on_gesture_callback = on_gesture_callback

        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

        self._cap = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Debounce state: last gesture name -> timestamp
        self._last_gesture = {}
        self._last_gesture_time = {}

        # Swipe tracking: per-hand wrist x history
        self._wrist_history = {"Left": deque(maxlen=SWIPE_HISTORY_SIZE),
                               "Right": deque(maxlen=SWIPE_HISTORY_SIZE)}

        logger.info("[Gesture] GestureController initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Begin camera capture in a background daemon thread."""
        if self._running:
            logger.warning("[Gesture] Already running")
            return

        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            logger.error("[Gesture] Cannot open camera (index 0)")
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("[Gesture] Camera capture started (daemon thread)")

    def stop(self):
        """Stop camera capture and release resources."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("[Gesture] Camera capture stopped")

    def process_frame(self, frame: np.ndarray):
        """Process an externally-provided BGR frame (e.g. shared with face_auth).

        Args:
            frame: BGR numpy array from cv2.
        """
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hands.process(rgb)
        self._handle_results(results)

    # ------------------------------------------------------------------
    # Internal capture loop
    # ------------------------------------------------------------------

    def _capture_loop(self):
        """Background thread: grab frames at ~TARGET_FPS and process them."""
        interval = 1.0 / TARGET_FPS
        logger.info("[Gesture] Capture loop running at ~%d fps", TARGET_FPS)

        while self._running:
            loop_start = time.monotonic()

            ret, frame = self._cap.read()
            if not ret:
                logger.warning("[Gesture] Frame read failed, retrying...")
                time.sleep(0.1)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._hands.process(rgb)
            self._handle_results(results)

            # Throttle to target FPS
            elapsed = time.monotonic() - loop_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("[Gesture] Capture loop exited")

    # ------------------------------------------------------------------
    # Results handling
    # ------------------------------------------------------------------

    def _handle_results(self, results):
        """Process MediaPipe hand results and fire callbacks."""
        if not results or not results.multi_hand_landmarks:
            return

        for hand_landmarks, handedness_info in zip(
            results.multi_hand_landmarks, results.multi_handedness
        ):
            hand_label = handedness_info.classification[0].label  # "Left" or "Right"
            confidence = handedness_info.classification[0].score

            gesture = self._detect_gesture(hand_landmarks, hand_label)
            if gesture is None:
                continue

            # Debounce: skip if same gesture fired within DEBOUNCE_SECONDS
            now = time.monotonic()
            key = f"{hand_label}_{gesture}"
            last_time = self._last_gesture_time.get(key, 0.0)
            if now - last_time < DEBOUNCE_SECONDS:
                continue

            self._last_gesture_time[key] = now

            payload = {
                "gesture": gesture,
                "confidence": round(float(confidence), 3),
                "hand": hand_label.lower(),  # 'left' | 'right'
            }

            logger.info("[Gesture] Detected: %s (hand=%s, conf=%.2f)",
                        gesture, hand_label.lower(), confidence)

            if self.on_gesture_callback is not None:
                try:
                    self.on_gesture_callback(payload)
                except Exception:
                    logger.exception("[Gesture] Callback error")

    # ------------------------------------------------------------------
    # Gesture detection
    # ------------------------------------------------------------------

    def _detect_gesture(self, hand_landmarks, hand_label="Right"):
        """Classify the current hand pose into a gesture name.

        Args:
            hand_landmarks: MediaPipe NormalizedLandmarkList (21 landmarks).
            hand_label: 'Left' or 'Right' for swipe tracking.

        Returns:
            Gesture name string or None if no gesture matched.
        """
        lm = hand_landmarks.landmark

        # --- Helper: check if a finger is extended (tip.y < pip.y) ---
        def finger_extended(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y

        # --- Helper: thumb extended (use x-axis, direction depends on hand) ---
        def thumb_extended():
            # Thumb tip further from palm center than thumb IP in x
            if hand_label == "Right":
                return lm[THUMB_TIP].x < lm[THUMB_IP].x
            else:
                return lm[THUMB_TIP].x > lm[THUMB_IP].x

        # --- Compute finger states ---
        fingers = [finger_extended(t, p) for t, p in zip(FINGER_TIPS, FINGER_PIPS)]
        index_ext, middle_ext, ring_ext, pinky_ext = fingers
        thumb_ext = thumb_extended()
        num_fingers_extended = sum(fingers)

        # --- Pinch: thumb tip to index tip distance ---
        dx = lm[THUMB_TIP].x - lm[INDEX_TIP].x
        dy = lm[THUMB_TIP].y - lm[INDEX_TIP].y
        dz = lm[THUMB_TIP].z - lm[INDEX_TIP].z
        pinch_dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if pinch_dist < PINCH_THRESHOLD:
            return "pinch"

        # --- Thumbs up: thumb pointing up, all other fingers closed ---
        if thumb_ext and num_fingers_extended == 0 and lm[THUMB_TIP].y < lm[THUMB_MCP].y:
            return "thumbs_up"

        # --- Swipe detection via wrist x-position history ---
        wrist_x = lm[WRIST].x
        history = self._wrist_history[hand_label]
        history.append((time.monotonic(), wrist_x))

        if len(history) >= SWIPE_HISTORY_SIZE:
            oldest_t, oldest_x = history[0]
            newest_t, newest_x = history[-1]
            dt = newest_t - oldest_t
            if 0 < dt < 1.0:  # within 1 second window
                delta_x = newest_x - oldest_x
                if delta_x > SWIPE_THRESHOLD:
                    history.clear()
                    return "swipe_right"
                elif delta_x < -SWIPE_THRESHOLD:
                    history.clear()
                    return "swipe_left"

        # --- Open palm: all 4 fingers extended ---
        if num_fingers_extended == 4:
            return "open_palm"

        # --- Fist: no fingers extended ---
        if num_fingers_extended == 0 and not thumb_ext:
            return "fist"

        # --- Point up: only index extended ---
        if index_ext and not middle_ext and not ring_ext and not pinky_ext:
            return "point_up"

        # --- Peace: index + middle extended, others closed ---
        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return "peace"

        return None


# ----------------------------------------------------------------------
# Standalone test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    def _on_gesture(payload):
        print(f"  >> GESTURE: {payload}")

    ctrl = GestureController(on_gesture_callback=_on_gesture)
    ctrl.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.stop()
        print("Done.")
