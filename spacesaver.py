import os
import sys
import hashlib
import zipfile
import json
import shutil
import datetime
import platform
import psutil
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QHBoxLayout, QMessageBox, QAbstractItemView, QCheckBox, QLabel, QLineEdit,
    QComboBox, QToolTip
)
from PyQt5.QtGui import QColor, QFont, QBrush, QPixmap, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal

EXCLUDED_DIRS = [
    os.environ.get('SystemRoot', 'C:/Windows'),
    os.environ.get('ProgramFiles', 'C:/Program Files'),
    os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'),
    os.environ.get('APPDATA', ''),
    os.environ.get('LOCALAPPDATA', '')
]

COMMON_EXTENSIONS = [
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff',
    '.zip', '.rar', '.7z', '.exe', '.msi', '.dmg', '.pkg',
    '.pdf', '.docx', '.pptx', '.xls', '.xlsx', '.txt',
    '.psd', '.ai', '.svg', '.blend', '.skp', '.cad'
]

def human_readable_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

class FileScanner(QThread):
    progress = pyqtSignal(int)
    file_found = pyqtSignal(str, int, str, str, str)
    finished = pyqtSignal()
    status = pyqtSignal(str)

    def __init__(self, folder, extensions):
        super().__init__()
        self.folder = folder
        self.extensions = extensions
        self._is_paused = False
        self._is_running = True
        self.found_hashes = {}

    def run(self):
        total_files = 0
        file_list = []
        for root, dirs, files in os.walk(self.folder):
            if any(root.startswith(ex) for ex in EXCLUDED_DIRS):
                continue
            for file in files:
                total_files += 1
                file_list.append(os.path.join(root, file))

        for idx, path in enumerate(file_list):
            if not self._is_running:
                break
            while self._is_paused:
                self.msleep(100)
            try:
                size = os.path.getsize(path)
                ext = os.path.splitext(path)[1].lower()
                if (not self.extensions or ext in self.extensions) and size > 512 * 1024:
                    hashval = self.hash_file(path)
                    duplicate_of = self.found_hashes.get(hashval, '')
                    if not duplicate_of:
                        self.found_hashes[hashval] = path
                    self.file_found.emit(os.path.basename(path), size, path, 'No', duplicate_of)
            except Exception:
                continue
            self.progress.emit(int((idx + 1) / total_files * 100))
        self.finished.emit()

    def hash_file(self, path):
        hasher = hashlib.sha256()
        try:
            with open(path, 'rb') as afile:
                while chunk := afile.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except:
            return ''

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def stop(self):
        self._is_running = False

class CleanupApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Futuristic File Cleanup")
        self.setStyleSheet("""
            QPushButton {
                background-color: #E30613; color: white; border: none; padding: 8px 16px;
                font-weight: bold; border-radius: 8px;
            }
            QPushButton:hover { background-color: #B00010; }
            QTableWidget { background-color: #1c1c1c; color: white; gridline-color: gray; }
            QHeaderView::section {
                background-color: #000000; color: white; font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #2b2b2b; color: white; border-radius: 4px; padding: 4px;
            }
        """)

        layout = QVBoxLayout()

        self.drive_label = QLabel("Drive Usage: Calculating...")
        self.drive_progress = QProgressBar()
        self.drive_progress.setMaximum(100)
        self.drive_progress.setValue(0)

        layout.addWidget(self.drive_label)
        layout.addWidget(self.drive_progress)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Select", "Filename", "Size", "Path", "Archived", "Last Modified", "Duplicate Of"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_table)

        header = self.table.horizontalHeader()
        header.sectionClicked.connect(self.handle_header_click)

        control_layout = QHBoxLayout()
        self.ext_box = QComboBox()
        self.ext_box.addItem("All")
        for ext in COMMON_EXTENSIONS:
            self.ext_box.addItem(ext)

        scan_btn = QPushButton("Scan for Space")
        scan_btn.clicked.connect(self.scan_files)

        self.progress = QProgressBar()
        self.progress.setValue(0)

        self.status = QLabel("")
        self.space_saved_label = QLabel("Space to be freed: 0.00 MB")

        control_layout.addWidget(QLabel("File Type:"))
        control_layout.addWidget(self.ext_box)
        control_layout.addWidget(scan_btn)
        control_layout.addWidget(self.progress)
        control_layout.addWidget(self.status)

        action_layout = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)

        move_btn = QPushButton("Move Selected")
        move_btn.clicked.connect(self.move_selected)

        archive_btn = QPushButton("Archive Selected")
        archive_btn.clicked.connect(self.archive_selected)

        action_layout.addWidget(delete_btn)
        action_layout.addWidget(move_btn)
        action_layout.addWidget(archive_btn)
        action_layout.addWidget(self.space_saved_label)

        layout.addLayout(control_layout)
        layout.addWidget(self.table)
        layout.addLayout(action_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.update_drive_usage()

    def update_drive_usage(self):
        partition = os.path.abspath(os.sep)
        usage = psutil.disk_usage(partition)
        used_percent = int(usage.percent)
        self.drive_label.setText(f"Drive Usage: {used_percent}% used — {human_readable_size(usage.used)} of {human_readable_size(usage.total)}")
        self.drive_progress.setValue(used_percent)

    def sort_table(self, idx):
        self.table.sortItems(idx)

    def handle_header_click(self, idx):
        if idx == 0:  # Select column
            new_state = not all(self.table.cellWidget(row, 0).isChecked() for row in range(self.table.rowCount()))
            for row in range(self.table.rowCount()):
                self.table.cellWidget(row, 0).setChecked(new_state)
            self.update_space_label()

    def scan_files(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if not folder:
            return
        ext = self.ext_box.currentText()
        ext_filter = [] if ext == "All" else [ext]
        self.table.setRowCount(0)
        self.scanner = FileScanner(folder, ext_filter)
        self.scanner.file_found.connect(self.add_file)
        self.scanner.progress.connect(self.progress.setValue)
        self.scanner.status.connect(self.status.setText)
        self.scanner.finished.connect(lambda: self.status.setText("Done."))
        self.scanner.start()

    def add_file(self, name, size, path, archived, duplicate_of):
        row = self.table.rowCount()
        self.table.insertRow(row)
        chk = QCheckBox()
        chk.stateChanged.connect(self.update_space_label)
        self.table.setCellWidget(row, 0, chk)
        self.table.setItem(row, 1, QTableWidgetItem(name))
        self.table.setItem(row, 2, QTableWidgetItem(human_readable_size(size)))
        self.table.setItem(row, 3, QTableWidgetItem(path))
        self.table.setItem(row, 4, QTableWidgetItem(archived))
        try:
            mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
        except:
            mod_time = ""
        self.table.setItem(row, 5, QTableWidgetItem(mod_time))
        self.table.setItem(row, 6, QTableWidgetItem(duplicate_of))

        if duplicate_of:
            for col in range(7):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setBackground(QColor("#800000"))

        # Tooltip preview for images or PDF
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            pixmap = QPixmap(path).scaledToWidth(200, Qt.SmoothTransformation)
            self.table.item(row, 1).setToolTip(f"<img src='{path}' width='200'>")
        elif ext == '.pdf':
            self.table.item(row, 1).setToolTip("PDF File - Preview not available yet")
        else:
            self.table.item(row, 1).setToolTip("File type not supported for preview")

    def update_space_label(self):
        total = 0
        for i in self.get_selected_rows():
            try:
                size_text = self.table.item(i, 2).text()
                size_mb = float(size_text.split()[0])  # Assume "x.xx MB"
                total += size_mb
            except:
                continue
        self.space_saved_label.setText(f"Space to be freed: {total:.2f} MB")

    def get_selected_rows(self):
        return [i for i in range(self.table.rowCount()) if self.table.cellWidget(i, 0).isChecked()]

    def delete_selected(self):
        for i in reversed(self.get_selected_rows()):
            path = self.table.item(i, 3).text()
            try:
                os.remove(path)
                self.table.removeRow(i)
            except:
                continue
        self.update_space_label()

    def move_selected(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination")
        if not folder:
            return
        for i in self.get_selected_rows():
            path = self.table.item(i, 3).text()
            try:
                shutil.move(path, folder)
                self.table.item(i, 3).setText(os.path.join(folder, os.path.basename(path)))
            except:
                continue

    def archive_selected(self):
        archive_dir = os.path.expanduser("~/Documents/ImageCleanup_Archives")
        os.makedirs(archive_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(archive_dir, f"archive_{timestamp}.zip")
        manifest = {}
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for i in self.get_selected_rows():
                path = self.table.item(i, 3).text()
                arcname = os.path.basename(path)
                try:
                    zf.write(path, arcname)
                    manifest[arcname] = path
                    os.remove(path)
                    self.table.item(i, 4).setText("Yes")
                except:
                    continue
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        self.update_space_label()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CleanupApp()
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec_())
