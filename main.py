#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 批量操作工具 — 入口

启动:
    cd ~/Desktop/HttpTool
    python main.py

打包:
    pip install pyinstaller
    pyinstaller --onefile --windowed --name "HttpTool" main.py
"""

import sys
import os

# 确保能加载同目录下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("HttpTool")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
