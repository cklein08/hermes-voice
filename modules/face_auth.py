"""
Face Authentication Module for Hermes Voice Assistant
Uses MediaPipe Face Landmarker (478 landmarks) + cosine similarity.
All local — no cloud APIs.
"""

import base64
import os
import platform
import sys
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# MediaPipe imports
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

PREFIX = "[FaceAuth]"

# MediaPipe Face Landmarker model
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_DIR = Path(__file__).parent / "models"
MODEL_PATH = MODEL_DIR / "face_landmarker.task"

AUTH_THRESHOLD = 0.85


def _log(msg: str):
    print(f"{PREFIX} {msg}", flush=True)


def _ensure_model():
    """Download face_landmarker.task if not already present."""
    if MODEL_PATH.exists():
        return str(MODEL_PATH)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    _log(f"Downloading face landmarker model to {MODEL_PATH} ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, str(MODEL_PATH))
        _log("Model downloaded successfully.")
    except Exception as e:
        _log(f"ERROR downloading model: {e}")
        raise
    return str(MODEL_PATH)


def _landmarks_to_vector(landmarks) -> np.ndarray:
    """Flatten 478 face landmarks (x, y, z) into a 1D numpy vector."""
    coords = []
    for lm in landmarks:
        coords.extend([lm.x, lm.y, lm.z])
    return np.array(coords, dtype=np.float64)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _create_landmarker():
    """Create and return a MediaPipe FaceLandmarker instance."""
    model_path = _ensure_model()
    base_options = mp_python.BaseOptions(model_asset_path=model_path)
    options = mp_vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return mp_vision.FaceLandmarker.create_from_options(options)


def _extract_landmarks_from_image(image_rgb: np.ndarray, landmarker=None):
    """Extract face landmarks from an RGB numpy image.
    Returns landmark vector or None if no face found.
    If landmarker is None, creates a temporary one.
    """
    own_landmarker = False
    if landmarker is None:
        landmarker = _create_landmarker()
        own_landmarker = True
    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
        result = landmarker.detect(mp_image)
        if not result.face_landmarks:
            return None
        return _landmarks_to_vector(result.face_landmarks[0])
    finally:
        if own_landmarker:
            landmarker.close()


def _open_camera(index=0):
    """Open camera, handling macOS (CAP_AVFOUNDATION) vs Linux gracefully."""
    system = platform.system()
    cap = None
    if system == "Darwin":
        # macOS: prefer AVFoundation backend
        _log("macOS detected — using CAP_AVFOUNDATION backend")
        cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            _log("AVFoundation failed, falling back to default backend")
            cap = cv2.VideoCapture(index)
    else:
        # Linux / other
        cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        _log("ERROR: Could not open camera")
        return None

    # Set modest resolution for speed
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


class FaceAuthenticator:
    """Face authentication using MediaPipe Face Landmarker + cosine similarity."""

    def __init__(self, reference_path: str, on_status_callback=None):
        """
        Args:
            reference_path: Path to reference JPEG image of the authorized user.
            on_status_callback: Optional callable(dict) invoked on auth events.
        """
        self.reference_path = Path(reference_path)
        self.on_status_callback = on_status_callback
        self.threshold = AUTH_THRESHOLD

        self._reference_vector = None
        self._landmarker = None
        self._cap = None
        self._running = False
        self._thread = None
        self._current_frame = None  # latest BGR frame from camera
        self._lock = threading.Lock()
        self._authenticated = False

        # Load model + reference on init
        try:
            self._landmarker = _create_landmarker()
            _log("Face landmarker initialized.")
        except Exception as e:
            _log(f"ERROR initializing landmarker: {e}")

        self._load_reference()

    def _load_reference(self):
        """Load and extract landmarks from the reference image."""
        if not self.reference_path.exists():
            _log(f"WARNING: Reference image not found at {self.reference_path}")
            self._reference_vector = None
            return

        try:
            img_bgr = cv2.imread(str(self.reference_path))
            if img_bgr is None:
                _log(f"ERROR: Could not read reference image: {self.reference_path}")
                self._reference_vector = None
                return
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            vec = _extract_landmarks_from_image(img_rgb, self._landmarker)
            if vec is None:
                _log("WARNING: No face detected in reference image!")
                self._reference_vector = None
            else:
                self._reference_vector = vec
                _log(f"Reference face loaded ({len(vec)} values) from {self.reference_path}")
        except Exception as e:
            _log(f"ERROR loading reference: {e}")
            self._reference_vector = None

    def start(self):
        """Begin camera capture in a background daemon thread (~10fps)."""
        if self._running:
            _log("Camera already running.")
            return

        self._cap = _open_camera(0)
        if self._cap is None:
            _log("ERROR: Cannot start — camera not available.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        _log("Camera capture started.")

    def _capture_loop(self):
        """Background thread: grab frames at ~10fps."""
        while self._running:
            try:
                if self._cap is None or not self._cap.isOpened():
                    _log("Camera lost, stopping capture loop.")
                    break
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    with self._lock:
                        self._current_frame = frame
                else:
                    _log("WARNING: Failed to read frame from camera.")
            except Exception as e:
                _log(f"ERROR in capture loop: {e}")
            time.sleep(0.1)  # ~10fps

        self._running = False
        _log("Capture loop exited.")

    def stop(self):
        """Stop camera capture and release resources."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        _log("Camera stopped.")

    def check_frame(self, frame_bytes: bytes = None) -> tuple:
        """Check a single frame for face match.

        Args:
            frame_bytes: Optional raw JPEG/PNG bytes. If None, uses current camera frame.

        Returns:
            (authenticated: bool, similarity: float)
        """
        if self._reference_vector is None:
            _log("No reference vector loaded — cannot authenticate.")
            return (False, 0.0)

        # Get the frame to check
        frame_bgr = None
        if frame_bytes is not None:
            try:
                arr = np.frombuffer(frame_bytes, dtype=np.uint8)
                frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as e:
                _log(f"ERROR decoding frame_bytes: {e}")
                return (False, 0.0)
        else:
            with self._lock:
                if self._current_frame is not None:
                    frame_bgr = self._current_frame.copy()

        if frame_bgr is None:
            return (False, 0.0)

        # Extract landmarks
        try:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            vec = _extract_landmarks_from_image(frame_rgb, self._landmarker)
        except Exception as e:
            _log(f"ERROR extracting landmarks: {e}")
            return (False, 0.0)

        if vec is None:
            return (False, 0.0)

        # Compare
        similarity = _cosine_similarity(self._reference_vector, vec)
        authenticated = similarity >= self.threshold

        if authenticated and not self._authenticated:
            _log(f"AUTHENTICATED (similarity={similarity:.4f})")
            self._authenticated = True
            if self.on_status_callback:
                try:
                    self.on_status_callback({
                        "authenticated": True,
                        "similarity": similarity,
                    })
                except Exception as e:
                    _log(f"ERROR in status callback: {e}")
        elif not authenticated:
            self._authenticated = False

        return (authenticated, similarity)

    def get_frame_base64(self) -> str:
        """Return the current camera frame as a base64-encoded JPEG string.
        Returns empty string if no frame available.
        """
        with self._lock:
            frame = self._current_frame

        if frame is None:
            return ""

        try:
            ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                return ""
            return base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception as e:
            _log(f"ERROR encoding frame to base64: {e}")
            return ""

    @classmethod
    def capture_reference(cls, save_path: str = None, camera_index: int = 0, countdown: int = 3):
        """Capture a photo from the webcam and save it as the reference image.

        Args:
            save_path: Where to save the reference JPEG. Defaults to modules/reference.jpg.
            camera_index: Camera device index.
            countdown: Seconds to wait before capture (gives user time to position).

        Returns:
            Path to saved reference image, or None on failure.
        """
        if save_path is None:
            save_path = str(Path(__file__).parent / "reference.jpg")

        _log(f"Capturing reference photo in {countdown} seconds...")
        cap = _open_camera(camera_index)
        if cap is None:
            _log("ERROR: Cannot open camera for reference capture.")
            return None

        try:
            # Warm up camera (some cameras need a few frames)
            for _ in range(10):
                cap.read()
                time.sleep(0.05)

            # Countdown
            for i in range(countdown, 0, -1):
                _log(f"  {i}...")
                time.sleep(1.0)
                # Keep reading to flush buffer
                cap.read()

            _log("Capturing now!")
            ret, frame = cap.read()
            if not ret or frame is None:
                _log("ERROR: Failed to capture frame.")
                return None

            # Verify a face is present
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            vec = _extract_landmarks_from_image(frame_rgb)
            if vec is None:
                _log("WARNING: No face detected in captured photo! Saving anyway.")
            else:
                _log(f"Face detected with {len(vec)} landmark values.")

            cv2.imwrite(save_path, frame)
            _log(f"Reference photo saved to {save_path}")
            return save_path

        except Exception as e:
            _log(f"ERROR during reference capture: {e}")
            return None
        finally:
            cap.release()

    def close(self):
        """Clean up all resources."""
        self.stop()
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                pass
            self._landmarker = None
        _log("Resources cleaned up.")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# --- CLI entry point for testing ---
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Face Authentication Module")
    parser.add_argument("--capture", action="store_true", help="Capture a reference photo")
    parser.add_argument("--reference", type=str, default=str(Path(__file__).parent / "reference.jpg"),
                        help="Path to reference image")
    parser.add_argument("--test", action="store_true", help="Run live authentication test")
    args = parser.parse_args()

    if args.capture:
        result = FaceAuthenticator.capture_reference(save_path=args.reference)
        if result:
            _log(f"Done! Reference saved to {result}")
        else:
            _log("Reference capture failed.")
            sys.exit(1)

    elif args.test:
        def on_status(status):
            _log(f"STATUS CALLBACK: {status}")

        auth = FaceAuthenticator(reference_path=args.reference, on_status_callback=on_status)
        auth.start()
        _log("Running live auth test — press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1.0)
                ok, sim = auth.check_frame()
                _log(f"  auth={ok}, similarity={sim:.4f}")
        except KeyboardInterrupt:
            _log("Interrupted.")
        finally:
            auth.close()

    else:
        parser.print_help()
