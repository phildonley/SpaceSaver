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
    QHBoxLayout, QLabel, QCheckBox, QComboBox
)
from PyQt5.QtGui import QColor, QPixmap
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
    '.psd', '.ai', '.svg', '.blend', '.skp', '.cad',
    '.sldprt', '.sldasm'
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

    def __init__(self, folder, extensions):
        super().__init__()
        self.folder = folder
        self.extensions = extensions
        self._is_running = True
        self.found_hashes = {}

    def run(self):
        file_list = []
        for root, dirs, files in os.walk(self.folder):
            if any(root.startswith(ex) for ex in EXCLUDED_DIRS):
                continue
            for f in files:
                file_list.append(os.path.join(root, f))

        total = len(file_list)
        for idx, path in enumerate(file_list):
            if not self._is_running:
                break
            try:
                size = os.path.getsize(path)
                ext = os.path.splitext(path)[1].lower()
                if (not self.extensions or ext in self.extensions) and size > 512 * 1024:
                    h = self.hash_file(path)
                    dup = self.found_hashes.get(h, '')
                    if not dup:
                        self.found_hashes[h] = path
                    self.file_found.emit(os.path.basename(path), size, path, 'No', dup)
            except:
                pass
            self.progress.emit(int((idx + 1) / total * 100))
        self.finished.emit()

    def hash_file(self, path):
        hasher = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except:
            return ''

    def stop(self):
        self._is_running = False

class CleanupApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Futuristic File Cleanup")
        self.setStyleSheet("""
            QPushButton { background-color: #E30613; color: white; border: none;
                          padding: 8px 16px; font-weight: bold; border-radius: 8px; }
            QPushButton:hover { background-color: #B00010; }
            QTableWidget { background-color: #1c1c1c; color: white; gridline-color: gray; }
            QHeaderView::section { background-color: #000; color: white; font-weight: bold; }
            QComboBox, QLineEdit { background-color: #2b2b2b; color: white; border-radius: 4px; padding: 4px; }
        """)

        self.last_checked_row = None

        # Drive usage
        self.drive_label = QLabel("Drive Usage: Calculating...")
        self.drive_progress = QProgressBar()
        self.drive_progress.setMaximum(100)
        self.drive_progress.setValue(0)
        self.update_drive_usage()

        # Table with 8 columns
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Select", "Filename", "Extension", "Size",
            "Path", "Archived", "Last Modified", "Duplicate Of"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(self.handle_header_click)

        # Controls
        self.ext_box = QComboBox()
        self.ext_box.addItem("All")
        for ext in COMMON_EXTENSIONS:
            self.ext_box.addItem(ext)

        scan_btn = QPushButton("Scan for Space")
        scan_btn.clicked.connect(self.scan_files)

        self.progress = QProgressBar()
        self.status = QLabel("")
        self.space_saved_label = QLabel("Space to be freed: 0.00 MB")

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("File Type:"))
        ctrl_layout.addWidget(self.ext_box)
        ctrl_layout.addWidget(scan_btn)
        ctrl_layout.addWidget(self.progress)
        ctrl_layout.addWidget(self.status)

        # Actions
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        move_btn = QPushButton("Move Selected")
        move_btn.clicked.connect(self.move_selected)
        archive_btn = QPushButton("Archive Selected")
        archive_btn.clicked.connect(self.archive_selected)

        act_layout = QHBoxLayout()
        act_layout.addWidget(delete_btn)
        act_layout.addWidget(move_btn)
        act_layout.addWidget(archive_btn)
        act_layout.addWidget(self.space_saved_label)

        # Assemble
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.drive_label)
        main_layout.addWidget(self.drive_progress)
        main_layout.addLayout(ctrl_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(act_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def update_drive_usage(self):
        part = os.path.abspath(os.sep)
        usage = psutil.disk_usage(part)
        pct = int(usage.percent)
        self.drive_label.setText(
            f"Drive Usage: {pct}% used — "
            f"{human_readable_size(usage.used)} of {human_readable_size(usage.total)}"
        )
        self.drive_progress.setValue(pct)

    def handle_header_click(self, idx):
        if idx == 0:
            # Toggle all checkboxes
            new = not all(
                self.table.cellWidget(r, 0).isChecked()
                for r in range(self.table.rowCount())
            )
            for r in range(self.table.rowCount()):
                self.table.cellWidget(r, 0).setChecked(new)
            self.update_space_label()

    def scan_files(self):
        downloads = os.path.expanduser("~/Downloads")
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", downloads
        )
        if not folder:
            return
        ext = self.ext_box.currentText()
        filt = [] if ext == "All" else [ext]
        self.table.setRowCount(0)
        self.scanner = FileScanner(folder, filt)
        self.scanner.file_found.connect(self.add_file)
        self.scanner.progress.connect(self.progress.setValue)
        self.scanner.finished.connect(lambda: self.status.setText("Done."))
        self.scanner.start()

    def add_file(self, name, size, path, archived, duplicate_of):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Checkbox with shift-click logic
        chk = QCheckBox()
        chk.clicked.connect(
            lambda *, r=row, c=chk.isChecked(): self.on_checkbox_clicked(r, c)
        )
        self.table.setCellWidget(row, 0, chk)

        # Filename, extension, size, etc.
        ext = os.path.splitext(path)[1].lower()
        mod_time = ""
        try:
            mod_time = datetime.datetime.fromtimestamp(
                os.path.getmtime(path)
            ).strftime('%Y-%m-%d %H:%M')
        except:
            pass

        self.table.setItem(row, 1, QTableWidgetItem(name))
        self.table.setItem(row, 2, QTableWidgetItem(ext))
        self.table.setItem(row, 3, QTableWidgetItem(human_readable_size(size)))
        self.table.setItem(row, 4, QTableWidgetItem(path))
        self.table.setItem(row, 5, QTableWidgetItem(archived))
        self.table.setItem(row, 6, QTableWidgetItem(mod_time))
        self.table.setItem(row, 7, QTableWidgetItem(duplicate_of))

        # Highlight duplicates
        if duplicate_of:
            for col in range(8):
                itm = self.table.item(row, col)
                if itm:
                    itm.setBackground(QColor("#800000"))

        # Inline thumbnail
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            pix = QPixmap(path).scaledToWidth(100, Qt.SmoothTransformation)
            self.table.item(row, 1).setData(Qt.DecorationRole, pix)

    def on_checkbox_clicked(self, row, checked):
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier and self.last_checked_row is not None:
            start = min(row, self.last_checked_row)
            end = max(row, self.last_checked_row)
            for r in range(start, end + 1):
                self.table.cellWidget(r, 0).setChecked(checked)
        self.last_checked_row = row
        self.update_space_label()

    def get_selected_rows(self):
        return [
            r for r in range(self.table.rowCount())
            if self.table.cellWidget(r, 0).isChecked()
        ]

    def update_space_label(self):
        unit_map = {
            'B': 1/(1024**2), 'KB': 1/1024,
            'MB': 1, 'GB': 1024, 'TB': 1024**2
        }
        total = 0.0
        for r in self.get_selected_rows():
            text = self.table.item(r, 3).text()  # Size column
            num, unit = text.split()
            total += float(num) * unit_map.get(unit, 1)
        self.space_saved_label.setText(f"Space to be freed: {total:.2f} MB")

    def delete_selected(self):
        for r in reversed(self.get_selected_rows()):
            path = self.table.item(r, 4).text()  # Path column
            try:
                os.remove(path)
                self.table.removeRow(r)
            except:
                pass
        self.update_space_label()

    def move_selected(self):
        dest = QFileDialog.getExistingDirectory(self, "Select Destination")
        if not dest:
            return
        for r in self.get_selected_rows():
            path = self.table.item(r, 4).text()
            try:
                newp = shutil.move(path, dest)
                self.table.item(r, 4).setText(newp)
            except:
                pass

    def archive_selected(self):
        archive_dir = os.path.expanduser("~/Documents/ImageCleanup_Archives")
        os.makedirs(archive_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(archive_dir, f"archive_{stamp}.zip")
        manifest = {}
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for r in self.get_selected_rows():
                path = self.table.item(r, 4).text()
                name = os.path.basename(path)
                try:
                    zf.write(path, name)
                    manifest[name] = path
                    os.remove(path)
                    self.table.item(r, 5).setText("Yes")
                except:
                    pass
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        self.update_space_label()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = CleanupApp()
    w.resize(1200, 800)
    w.show()
    sys.exit(app.exec_())
