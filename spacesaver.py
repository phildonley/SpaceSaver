import os
import sys
import hashlib
import zipfile
import json
import shutil
import datetime
import psutil
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QHBoxLayout, QLabel, QCheckBox, QComboBox
)
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# --- Configuration ----------------------------------------------------------

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

# --- File scanning thread ---------------------------------------------------

class FileScanner(QThread):
    progress    = pyqtSignal(int)
    file_found  = pyqtSignal(str, int, str, str, str)
    finished    = pyqtSignal()

    def __init__(self, folder, extensions):
        super().__init__()
        self.folder       = folder
        self.extensions   = extensions
        self._is_running  = True
        self.found_hashes = {}

    def run(self):
        # Gather all files under the folder
        file_list = []
        for root, dirs, files in os.walk(self.folder):
            if any(root.startswith(ex) for ex in EXCLUDED_DIRS):
                continue
            for f in files:
                file_list.append(os.path.join(root, f))

        total = len(file_list)
        print(f"[DEBUG] Scanning folder {self.folder!r}, found {total} files")
        # Process each file
        for idx, path in enumerate(file_list):
            if not self._is_running:
                break
            try:
                size = os.path.getsize(path)
                ext  = os.path.splitext(path)[1].lower()
                print(f"[DEBUG] {idx+1}/{total}: {path!r} -> ext={ext}, size={size} bytes")

                # Only filter by extension now (no 512 KB cutoff)
                if not self.extensions or ext in self.extensions:
                    h   = self.hash_file(path)
                    dup = self.found_hashes.get(h, '')
                    if not dup:
                        self.found_hashes[h] = path
                    print(f"[DEBUG] Emitting file_found for {path!r}")
                    self.file_found.emit(
                        os.path.basename(path),
                        size,
                        path,
                        'No',
                        dup
                    )
            except Exception as e:
                print(f"[DEBUG] Error processing {path!r}: {e}")

            # Update progress bar
            self.progress.emit(int((idx + 1) / total * 100))

        print("[DEBUG] Scan complete, emitting finished")
        self.finished.emit()

    def hash_file(self, path):
        hasher = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ''

    def stop(self):
        self._is_running = False

# --- Main application window ------------------------------------------------

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
            QComboBox, QLineEdit { background-color: #2b2b2b; color: white;
                                  border-radius: 4px; padding: 4px; }
        """)

        self.last_checked_row = None

        # Drive usage UI
        self.drive_label    = QLabel("Drive Usage: Calculating...")
        self.drive_progress = QProgressBar()
        self.drive_progress.setMaximum(100)
        self.update_drive_usage()

        # Table setup with 8 columns
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Select", "Filename", "Extension", "Size",
            "Path", "Archived", "Last Modified", "Duplicate Of"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(self.handle_header_click)

        # Filter combo-box
        self.ext_box = QComboBox()
        self.ext_box.addItem("All")
        for ext in COMMON_EXTENSIONS:
            self.ext_box.addItem(ext)

        # Scan button and progress
        scan_btn = QPushButton("Scan for Space")
        scan_btn.clicked.connect(self.scan_files)
        self.progress = QProgressBar()
        self.status   = QLabel("")
        self.space_saved_label = QLabel("Space to be freed: 0.00 MB")

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("File Type:"))
        ctrl_layout.addWidget(self.ext_box)
        ctrl_layout.addWidget(scan_btn)
        ctrl_layout.addWidget(self.progress)
        ctrl_layout.addWidget(self.status)

        # Action buttons
        delete_btn  = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        move_btn    = QPushButton("Move Selected")
        move_btn.clicked.connect(self.move_selected)
        archive_btn = QPushButton("Archive Selected")
        archive_btn.clicked.connect(self.archive_selected)

        act_layout = QHBoxLayout()
        act_layout.addWidget(delete_btn)
        act_layout.addWidget(move_btn)
        act_layout.addWidget(archive_btn)
        act_layout.addWidget(self.space_saved_label)

        # Assemble main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.drive_label)
        main_layout.addWidget(self.drive_progress)
        main_layout.addLayout(ctrl_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(act_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        print("[DEBUG] UI initialized")

    def update_drive_usage(self):
        part  = os.path.abspath(os.sep)
        usage = psutil.disk_usage(part)
        pct   = int(usage.percent)
        self.drive_label.setText(
            f"Drive Usage: {pct}% used — "
            f"{human_readable_size(usage.used)} of {human_readable_size(usage.total)}"
        )
        self.drive_progress.setValue(pct)

    def handle_header_click(self, idx):
        if idx == 0:
            # Toggle all checkboxes
            new_state = not all(
                self.table.cellWidget(r, 0).isChecked()
                for r in range(self.table.rowCount())
            )
            for r in range(self.table.rowCount()):
                self.table.cellWidget(r, 0).setChecked(new_state)
            self.update_space_label()

    def scan_files(self):
        downloads = os.path.expanduser("~/Downloads")
        folder    = QFileDialog.getExistingDirectory(
            self, "Select Folder", downloads
        )
        print(f"[DEBUG] scan_files called, folder selected: {folder!r}")
        if not folder:
            print("[DEBUG] No folder selected, aborting scan")
            return

        ext  = self.ext_box.currentText()
        filt = [] if ext == "All" else [ext]
        print(f"[DEBUG] Filtering for extensions: {filt}")

        self.table.setRowCount(0)
        self.scanner = FileScanner(folder, filt)
        self.scanner.file_found.connect(self.add_file)
        print("[DEBUG] Connected file_found → add_file")
        self.scanner.progress.connect(self.progress.setValue)
        self.scanner.finished.connect(lambda: self.status.setText("Done."))
        self.scanner.start()

    def add_file(self, name, size, path, archived, duplicate_of):
        print(f"[DEBUG] add_file received: {path!r}")
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Checkbox with shift-click support
        chk = QCheckBox()
        chk.clicked.connect(
            lambda _, r=row, c=chk.isChecked(): self.on_checkbox_clicked(r, c)
        )
        self.table.setCellWidget(row, 0, chk)

        # File metadata
        ext = os.path.splitext(path)[1].lower()
        try:
            mod_time = datetime.datetime.fromtimestamp(
                os.path.getmtime(path)
            ).strftime('%Y-%m-%d %H:%M')
        except Exception:
            mod_time = ""

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

        # Inline thumbnail for images
        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            pix = QPixmap(path).scaledToWidth(100, Qt.SmoothTransformation)
            self.table.item(row, 1).setData(Qt.DecorationRole, pix)

    def on_checkbox_clicked(self, row, checked):
        print(f"[DEBUG] Checkbox clicked at row {row}, checked={checked}")
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier and self.last_checked_row is not None:
            start, end = sorted([row, self.last_checked_row])
            print(f"[DEBUG] Shift-select from {start} to {end}")
            for r in range(start, end + 1):
                self.table.cellWidget(r, 0).setChecked(checked)
        self.last_checked_row = row
        self.update_space_label()

    def get_selected_rows(self):
        selected = [
            r for r in range(self.table.rowCount())
            if self.table.cellWidget(r, 0).isChecked()
        ]
        print(f"[DEBUG] Selected rows: {selected}")
        return selected

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
        print(f"[DEBUG] update_space_label: total MB={total:.2f}")
        self.space_saved_label.setText(f"Space to be freed: {total:.2f} MB")

    def delete_selected(self):
        print("[DEBUG] delete_selected called")
        for r in reversed(self.get_selected_rows()):
            path = self.table.item(r, 4).text()
            try:
                os.remove(path)
                self.table.removeRow(r)
            except Exception as e:
                print(f"[DEBUG] Failed to delete {path!r}: {e}")
        self.update_space_label()

    def move_selected(self):
        print("[DEBUG] move_selected called")
        dest = QFileDialog.getExistingDirectory(self, "Select Destination")
        print(f"[DEBUG] Destination folder: {dest!r}")
        if not dest:
            return
        for r in self.get_selected_rows():
            path = self.table.item(r, 4).text()
            try:
                newp = shutil.move(path, dest)
                self.table.item(r, 4).setText(newp)
            except Exception as e:
                print(f"[DEBUG] Failed to move {path!r}: {e}")

    def archive_selected(self):
        print("[DEBUG] archive_selected called")
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
                except Exception as e:
                    print(f"[DEBUG] Failed to archive {path!r}: {e}")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        self.update_space_label()

# --- Application entry point -----------------------------------------------

if __name__ == "__main__":
    print("[DEBUG] Application starting")
    app = QApplication(sys.argv)
    window = CleanupApp()
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec_())
