"""Build the standalone GUI executable with PyInstaller."""

import PyInstaller.__main__


arguments = [
    "main.py",
    "--name=图片二值化",
    "--windowed",
    "--onefile",
    "--clean",
    "--noconfirm",
]

PyInstaller.__main__.run(arguments)
