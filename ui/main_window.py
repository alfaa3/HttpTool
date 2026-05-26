#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口 UI
"""

import os
import csv
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSpinBox, QLabel,
    QFileDialog, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor, QBrush

from core.worker import AccountWorker, WorkerSignals


class MainWindow(QMainWindow):
    COL_ACCOUNT = 0
    COL_PASSWORD = 1
    COL_CATEGORY = 2
    COL_STATUS = 3
    COL_DETAIL = 4

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HTTP 批量操作工具")
        self.resize(900, 600)

        # 线程池
        self.pool = QThreadPool()
        self._running = False   # 是否正在执行任务
        self._current_mode = None  # 'query' or 'apply'

        # 任务计数器
        self._total_tasks = 0
        self._done_tasks = 0

        # 构建界面
        self._build_ui()

    # ========== 构建界面 ==========

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)

        # ---- 顶部按钮栏 ----
        btn_bar = QHBoxLayout()

        self.btn_import = QPushButton("导入")
        self.btn_query = QPushButton("查询")
        self.btn_remove = QPushButton("剔除")
        self.btn_apply = QPushButton("申请")

        self.btn_import.clicked.connect(self._on_import)
        self.btn_query.clicked.connect(self._on_query)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_apply.clicked.connect(self._on_apply)

        btn_bar.addWidget(self.btn_import)
        btn_bar.addWidget(self.btn_query)
        btn_bar.addWidget(self.btn_remove)
        btn_bar.addWidget(self.btn_apply)

        btn_bar.addStretch()

        btn_bar.addWidget(QLabel("线程数:"))
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 50)
        self.spin_threads.setValue(5)
        self.spin_threads.setFixedWidth(60)
        btn_bar.addWidget(self.spin_threads)

        layout.addLayout(btn_bar)

        # ---- 表格 ----
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["账号", "密码", "分类", "状态", "详细信息"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_DETAIL, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # ---- 进度条 ----
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # ---- 初始状态 ----
        self._update_button_states()

    # ========== 按钮状态管理 ==========

    def _update_button_states(self):
        has_rows = self.table.rowCount() > 0
        self.btn_import.setEnabled(True)
        self.btn_remove.setEnabled(has_rows)

        if self._running:
            self.btn_query.setEnabled(False)
            self.btn_apply.setEnabled(False)
            self.spin_threads.setEnabled(False)
        else:
            self.btn_query.setEnabled(has_rows)
            self.btn_apply.setEnabled(has_rows)
            self.spin_threads.setEnabled(True)

    # ========== 导入 ==========

    def _on_import(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入账号文件",
            "",
            "支持的文件 (*.txt *.csv *.xlsx *.xls);;文本文件 (*.txt);;CSV (*.csv);;Excel (*.xlsx *.xls)"
        )
        if not file_path:
            return

        accounts = self._parse_file(file_path)
        if not accounts:
            QMessageBox.warning(self, "导入失败", f"未从文件中解析到账号数据\n\n支持格式:\n"
                                                   "txt: 每行 账号,密码,分类  或 账号\\t密码\\t分类\n"
                                                   "csv/xlsx: 包含 账号/密码/分类 列")
            return

        # 清空表格，填入数据
        self.table.setRowCount(len(accounts))
        for row, (account, password, category) in enumerate(accounts):
            for col, val in [(self.COL_ACCOUNT, account),
                             (self.COL_PASSWORD, password),
                             (self.COL_CATEGORY, category),
                             (self.COL_STATUS, ""),
                             (self.COL_DETAIL, "")]:
                item = QTableWidgetItem(val)
                item.setToolTip(val)
                self.table.setItem(row, col, item)

        self.progress.setValue(0)
        self._update_button_states()

    def _parse_file(self, filepath: str):
        """解析文件，返回 [(账号, 密码, 分类), ...]"""
        ext = Path(filepath).suffix.lower()
        results = []

        if ext == '.txt':
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t') if '\t' in line else line.split(',')
                    if len(parts) >= 2:
                        account = parts[0].strip()
                        password = parts[1].strip()
                        category = parts[2].strip() if len(parts) >= 3 else ""
                        if account:
                            results.append((account, password, category))

        elif ext == '.csv':
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                # 自动寻找账号/密码/分类列索引
                idx_acc = idx_pwd = idx_cat = -1
                if header:
                    for i, h in enumerate(h.lower() for h in header):
                        if '账号' in h or '账户' in h or 'account' in h or 'username' in h or 'user' in h:
                            idx_acc = i
                        elif '密码' in h or 'password' in h or 'pass' in h or 'pwd' in h:
                            idx_pwd = i
                        elif '分类' in h or '类别' in h or 'category' in h or 'cat' in h:
                            idx_cat = i
                else:
                    return results

                for row in reader:
                    if not row or len(row) < 2:
                        continue
                    account = row[idx_acc].strip() if idx_acc >= 0 and idx_acc < len(row) else row[0].strip()
                    password = row[idx_pwd].strip() if idx_pwd >= 0 and idx_pwd < len(row) else row[1].strip()
                    category = row[idx_cat].strip() if idx_cat >= 0 and idx_cat < len(row) else ""
                    if account:
                        results.append((account, password, category))

        elif ext in ('.xlsx', '.xls'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
                ws = wb.active
                rows_iter = ws.iter_rows(values_only=True)
                header = next(rows_iter, None)
                idx_acc = idx_pwd = idx_cat = -1
                if header:
                    for i, h in enumerate(str(h).lower() if h else "" for h in header):
                        if any(k in h for k in ('账号', '账户', 'account', 'username', 'user')):
                            idx_acc = i
                        elif any(k in h for k in ('密码', 'password', 'pass', 'pwd')):
                            idx_pwd = i
                        elif any(k in h for k in ('分类', '类别', 'category', 'cat')):
                            idx_cat = i
                else:
                    return results

                for row in rows_iter:
                    if not row:
                        continue
                    account = str(row[idx_acc]).strip() if idx_acc >= 0 and idx_acc < len(row) and row[idx_acc] else ""
                    password = str(row[idx_pwd]).strip() if idx_pwd >= 0 and idx_pwd < len(row) and row[idx_pwd] else ""
                    category = str(row[idx_cat]).strip() if idx_cat >= 0 and idx_cat < len(row) and row[idx_cat] else ""
                    if account:
                        results.append((account, password, category))

                wb.close()
            except ImportError:
                QMessageBox.critical(self, "缺少库", "解析 Excel 需要安装 openpyxl\n请执行: pip install openpyxl")
                return []
            except Exception as e:
                QMessageBox.warning(self, "解析失败", f"解析 Excel 文件出错:\n{e}")
                return []

        return results

    # ========== 查询 ==========

    def _on_query(self):
        self._start_tasks("query")

    # ========== 申请 ==========

    def _on_apply(self):
        self._start_tasks("apply")

    # ========== 剔除 ==========

    def _on_remove(self):
        """只保留未申请的，其余全部剔除"""
        row = self.table.rowCount() - 1
        while row >= 0:
            status_item = self.table.item(row, self.COL_STATUS)
            if status_item and status_item.text() == "未申请":
                row -= 1
                continue
            self.table.removeRow(row)
            row -= 1

        self._update_button_states()

    # ========== 批量启动任务 ==========

    def _start_tasks(self, mode: str):
        rows = self.table.rowCount()
        if rows == 0:
            return

        # 收集账号数据
        accounts = []
        for row in range(rows):
            account = self.table.item(row, self.COL_ACCOUNT)
            password = self.table.item(row, self.COL_PASSWORD)
            category = self.table.item(row, self.COL_CATEGORY)
            if account and password:
                accounts.append({
                    'row': row,
                    'account': account.text(),
                    'password': password.text(),
                    'category': category.text() if category else "",
                })

        if not accounts:
            return

        # 设置运行状态
        self._running = True
        self._current_mode = mode
        self._total_tasks = len(accounts)
        self._done_tasks = 0

        self.pool.setMaxThreadCount(self.spin_threads.value())
        self.progress.setMaximum(self._total_tasks)
        self.progress.setValue(0)

        # 清空旧的状态
        for row in range(rows):
            self.table.setItem(row, self.COL_STATUS, QTableWidgetItem(""))
            self.table.setItem(row, self.COL_DETAIL, QTableWidgetItem(""))

        self._update_button_states()

        # 启动每个账号的任务
        for acc in accounts:
            signals = WorkerSignals()
            worker = AccountWorker(
                account=acc['account'],
                password=acc['password'],
                category=acc['category'],
                mode=mode,
                signals=signals,
            )
            signals.result.connect(self._on_task_result)
            signals.finished.connect(self._on_task_finished)
            self.pool.start(worker)

        # 使用 QTimer 检测任务是否全部完成
        self._check_timer = QTimer()
        self._check_timer.setSingleShot(True)
        self._check_timer.timeout.connect(self._check_all_done)
        self._check_timer.start(500)

    def _on_task_result(self, account: str, password: str, category: str, status: str, detail: str):
        """单条任务结果回调（主线程执行）"""
        # 查找表格中对应的行
        for row in range(self.table.rowCount()):
            acc_item = self.table.item(row, self.COL_ACCOUNT)
            pwd_item = self.table.item(row, self.COL_PASSWORD)
            if acc_item and acc_item.text() == account and pwd_item and pwd_item.text() == password:
                status_item = QTableWidgetItem(status)
                status_item.setToolTip(status)
                self.table.setItem(row, self.COL_STATUS, status_item)

                detail_item = QTableWidgetItem(detail)
                detail_item.setToolTip(detail)
                self.table.setItem(row, self.COL_DETAIL, detail_item)

                # 状态着色
                self._color_status_row(row, status)
                break

        self._done_tasks += 1
        self.progress.setValue(self._done_tasks)

    def _color_status_row(self, row: int, status: str):
        """根据状态给行着色"""
        color_map = {
            "已申请":   QColor("#e8f5e9"),  # 浅绿
            "未申请":   QColor("#fff3e0"),  # 浅橙
            "未学习":   QColor("#e3f2fd"),  # 浅蓝
            "申请成功": QColor("#e8f5e9"),  # 浅绿
            "申请失败": QColor("#ffebee"),  # 浅红
            "登录失败": QColor("#ffebee"),  # 浅红
            "异常":     QColor("#fce4ec"),  # 浅粉
        }
        bg = color_map.get(status)
        if bg:
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(bg)

    def _on_task_finished(self):
        """单个 Worker 执行完毕"""
        pass  # 由定时器统一检测

    def _check_all_done(self):
        """检测所有任务是否完成"""
        if self.pool.activeThreadCount() == 0:
            mode_label = {"query": "查询", "apply": "申请"}.get(self._current_mode, "操作")
            self._running = False
            mode = self._current_mode
            self._current_mode = None
            self._update_button_states()
            self.progress.setValue(self.progress.maximum())
            QMessageBox.information(self, "完成", f"批量{mode_label}执行完毕")
        else:
            self._check_timer.start(500)

    # ========== 窗口关闭 ==========

    def closeEvent(self, event):
        if self._running:
            reply = QMessageBox.question(
                self, "确认退出",
                "任务正在执行中，确定退出吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()
