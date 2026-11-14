
import os
import shutil
import sys
from pathlib import Path

# Keep DLL directory handles alive
_DLL_HANDLES = []


def setup_ffmpeg():
    """Automatically detect and configure FFmpeg."""

    print("\nChecking FFmpeg installation...")

    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path:
        ffmpeg_exe = Path(ffmpeg_path).resolve()
        ffmpeg_dir = ffmpeg_exe.parent

        print(f"FFmpeg found in PATH: {ffmpeg_exe}")

    else:
        print("\nFFmpeg was not found in PATH.")

        user_path = input(
            "Enter FFmpeg bin folder or executable path: "
        ).strip().strip('"')

        if not user_path:
            raise RuntimeError(
                "FFmpeg is required. Please install FFmpeg "
                "and add it to PATH."
            )

        path = Path(user_path).expanduser().resolve()

        if path.is_dir():
            ffmpeg_dir = path
            ffmpeg_exe = ffmpeg_dir / (
                "ffmpeg.exe" if sys.platform == "win32"
                else "ffmpeg"
            )
        else:
            ffmpeg_exe = path
            ffmpeg_dir = path.parent

        if not ffmpeg_exe.is_file():
            raise RuntimeError(
                f"FFmpeg executable not found: {ffmpeg_exe}"
            )

    # Add FFmpeg directory to PATH only if necessary
    current_paths = os.environ.get("PATH", "").split(os.pathsep)

    if str(ffmpeg_dir) not in current_paths:
        os.environ["PATH"] = (
            str(ffmpeg_dir)
            + os.pathsep
            + os.environ.get("PATH", "")
        )

    # Register DLL directory on Windows
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        _DLL_HANDLES.append(
            os.add_dll_directory(str(ffmpeg_dir))
        )

    print(f"FFmpeg configured successfully: {ffmpeg_dir}")

    return True
