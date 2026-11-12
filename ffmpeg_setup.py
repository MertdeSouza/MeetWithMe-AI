
import os
import shutil
import sys
from pathlib import Path

# Keep DLL directory handles alive
_DLL_HANDLES = []


def setup_ffmpeg():

    print("\nChecking FFmpeg installation...")

    # 1. Check PATH
    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path:
        ffmpeg_dir = Path(ffmpeg_path).parent
        print(f"FFmpeg found in PATH: {ffmpeg_path}")

    else:
        print("\nFFmpeg was not found in PATH.")

        user_path = input(
            "Enter FFmpeg bin folder or executable path: "
        ).strip().strip('"')

        if not user_path:
            raise RuntimeError(
                "FFmpeg is required but was not found. "
                "Please install FFmpeg and add it to PATH."
            )

        path = Path(user_path).expanduser()

        if path.is_dir():
            ffmpeg_dir = path
            ffmpeg_exe = path / "ffmpeg.exe"

            if not ffmpeg_exe.exists():
                ffmpeg_exe = path / "ffmpeg"
        else:
            ffmpeg_exe = path
            ffmpeg_dir = path.parent

        if not ffmpeg_exe.exists():
            raise RuntimeError(
                f"FFmpeg executable not found at: {ffmpeg_exe}"
            )

    # 2. Add FFmpeg directory to PATH
    os.environ["PATH"] = (
        str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    )

    # 3. Register DLL directory and keep handle alive
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        _DLL_HANDLES.append(
            os.add_dll_directory(str(ffmpeg_dir))
        )

    print(f"FFmpeg configured successfully: {ffmpeg_dir}")

    return True
