"""Compatibility entry point; RGB-D capture implementation lives in rgbd_io."""
from .rgbd_io import image_array, info_dict, save_capture, stamp, ros_main as main

__all__ = ["image_array", "info_dict", "save_capture", "stamp", "main"]

if __name__ == "__main__":
    main()
