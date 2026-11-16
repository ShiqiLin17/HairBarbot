"""Small shared geometry for the camera (kept separate so the simulator doesn't need OpenCV)."""
import numpy as np


def head_to_cam_facing():
    """Rotation for a head looking straight at the camera: head x (forward) -> camera -z,
    head y (person's left) -> camera +x (image right, unmirrored), head z (up) -> camera -y."""
    return np.array([[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [-1.0, 0.0, 0.0]])
