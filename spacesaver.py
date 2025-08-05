import os
import sys
import subprocess
import hashlib
import zipfile
import json
import shutil
import datetime
import psutil
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
    QHBoxLayout, QLabel, QCheckBox, QComboBox, QMessageBox
)
from PyQt5.QtGui import QColor, QBrush
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
        file_list = []
        for root, dirs, files in os.walk(self.folder):
            if any(root.startswith(ex) for ex in EXCLUDED_DIRS):
                continue
            for f in files:
                file_list.append(os.path.join(root, f))

        total = len(file_list)
        print(f"[DEBUG] Scanning {self.folder!r}, found {total} files")
        for idx, path in enumerate(file_list):
            if not self._is_running:
                break
            try:
                size = os.path.getsize(path)
                ext  = os.path.splitext(path)[1].lower()
                print(f"[DEBUG] {idx+1}/{total}: {path!r} ext={ext} size={size}")
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
                print(f"[DEBUG] Error on {path!r}: {e}")

            self.progress.emit(int((idx + 1) / total * 100))

        print("[DEBUG] Scan complete")
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


# --- Main application window ------------------------------------------------

class CleanupApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Easy Archive")
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

        # Drive usage bar + colored chunks
        self.drive_label    = QLabel("Drive Usage: Calculating...")
        self.drive_progress = QProgressBar()
        self.drive_progress.setMaximum(100)
        self.update_drive_usage()

        # Table setup
        self.table = QTableWidget(0, 8)
        header_item = QTableWidgetItem("☐")
        header_item.setForeground(QBrush(QColor("white")))
        header_item.setTextAlignment(Qt.AlignCenter)
        self.table.setHorizontalHeaderItem(0, header_item)
        self.table.setHorizontalHeaderLabels([
            "", "Filename", "Extension", "Size",
            "Path", "Archived", "Last Modified", "Duplicate Of"
        ])
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(5, 60)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(self.handle_header_click)
        self.table.cellClicked.connect(self.on_cell_clicked)

        # Filter combo-box (wider)
        self.ext_box = QComboBox()
        self.ext_box.addItem("All")
        for ext in COMMON_EXTENSIONS:
            self.ext_box.addItem(ext)
        self.ext_box.setFixedWidth(self.ext_box.sizeHint().width() + 40)

        # Buttons and progress
        scan_btn = QPushButton("Scan for Space")
        scan_btn.clicked.connect(self.scan_files)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(self.progress.sizeHint().width() - 40)
        self.status   = QLabel("")
        self.space_saved_label = QLabel("Space to be freed: 0.00 MB")

        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(self.ext_box)
        ctrl_layout.addStretch()                       # push scan+progress right
        ctrl_layout.addWidget(scan_btn)
        ctrl_layout.addWidget(self.progress)
        ctrl_layout.addWidget(self.status)

        # Action buttons
        delete_btn   = QPushButton("Delete Selected");   delete_btn.clicked.connect(self.delete_selected)
        move_btn     = QPushButton("Move Selected");     move_btn.clicked.connect(self.move_selected)
        archive_btn  = QPushButton("Archive Selected");  archive_btn.clicked.connect(self.archive_selected)
        reverse_btn  = QPushButton("Reverse Archive");   reverse_btn.clicked.connect(self.reverse_archive)

        act_layout = QHBoxLayout()
        act_layout.addWidget(delete_btn)
        act_layout.addWidget(move_btn)
        act_layout.addWidget(archive_btn)
        act_layout.addWidget(reverse_btn)
        act_layout.addWidget(self.space_saved_label)

        # Main layout
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
        # color-code the progress bar
        if pct <= 70:
            color = "#00AA00"   # green
        elif pct <= 89:
            color = "#DDDD00"   # yellow
        else:
            color = "#FF3333"   # red
        self.drive_progress.setStyleSheet(f"""
            QProgressBar::chunk {{ background-color: {color}; }}
        """)
        self.drive_progress.setValue(pct)

    def handle_header_click(self, idx):
        if idx == 0:
            # disable updates for speed
            self.table.setSortingEnabled(False)
            self.table.setUpdatesEnabled(False)

            new_state = not all(
                self.table.cellWidget(r, 0).isChecked()
                for r in range(self.table.rowCount())
            )
            for r in range(self.table.rowCount()):
                self.table.cellWidget(r, 0).setChecked(new_state)
            symbol = "☑" if new_state else "☐"
            self.table.horizontalHeaderItem(0).setText(symbol)
            self.update_space_label()

            # re-enable
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(True)

    def scan_files(self):
        downloads = os.path.expanduser("~/Downloads")
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", downloads, QFileDialog.ShowDirsOnly
        )
        print(f"[DEBUG] scan_files → folder: {folder!r}")
        if not folder:
            return

        ext  = self.ext_box.currentText()
        filt = [] if ext == "All" else [ext]
        print(f"[DEBUG] Filtering: {filt}")

        # prepare UI
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        self.scanner = FileScanner(folder, filt)
        self.scanner.file_found.connect(self.add_file)
        self.scanner.progress.connect(self.progress.setValue)
        self.scanner.finished.connect(self.on_scan_complete)
        self.scanner.start()

    def on_scan_complete(self):
        self.status.setText("Done.")
        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)

    def add_file(self, name, size, path, archived, duplicate_of):
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk = QCheckBox()
        chk.stateChanged.connect(
            lambda state, r=row: self.on_checkbox_clicked(r, state == Qt.Checked)
        )
        self.table.setCellWidget(row, 0, chk)

        item_name = QTableWidgetItem(name)
        if os.path.splitext(path)[1].lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
            item_name.setToolTip(f"<img src='{path}' width='200'>")
        self.table.setItem(row, 1, item_name)

        ext = os.path.splitext(path)[1].lower()
        self.table.setItem(row, 2, QTableWidgetItem(ext))
        self.table.setItem(row, 3, QTableWidgetItem(human_readable_size(size)))

        max_len = 60
        display = path if len(path) <= max_len else f"...{path[-(max_len-3):]}"
        item_path = QTableWidgetItem(display)
        item_path.setToolTip(path)
        self.table.setItem(row, 4, item_path)

        self.table.setItem(row, 5, QTableWidgetItem(archived))
        try:
            mod_time = datetime.datetime.fromtimestamp(
                os.path.getmtime(path)
            ).strftime('%Y-%m-%d %H:%M')
        except:
            mod_time = ""
        self.table.setItem(row, 6, QTableWidgetItem(mod_time))
        self.table.setItem(row, 7, QTableWidgetItem(duplicate_of))

        if duplicate_of:
            for col in range(8):
                itm = self.table.item(row, col)
                if itm:
                    itm.setBackground(QColor("#800000"))

    def on_checkbox_clicked(self, row, checked):
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier and self.last_checked_row is not None:
            start, end = sorted([row, self.last_checked_row])
            for r in range(start, end + 1):
                chk = self.table.cellWidget(r, 0)
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
        self.last_checked_row = row
        self.update_space_label()

    def on_cell_clicked(self, row, col):
        if col == 4:
            full = self.table.item(row, 4).toolTip()
            folder = os.path.dirname(full)
            try:
                if sys.platform.startswith('win'):
                    os.startfile(folder)
                elif sys.platform.startswith('darwin'):
                    subprocess.Popen(['open', folder])
                else:
                    subprocess.Popen(['xdg-open', folder])
            except:
                pass

    def get_selected_rows(self):
        return [r for r in range(self.table.rowCount())
                if self.table.cellWidget(r, 0).isChecked()]

    def update_space_label(self):
        unit_map = {'B':1/1024**2, 'KB':1/1024, 'MB':1, 'GB':1024, 'TB':1024**2}
        total = 0.0
        for r in self.get_selected_rows():
            text = self.table.item(r, 3).text()
            num, unit = text.split()
            total += float(num) * unit_map.get(unit, 1)
        self.space_saved_label.setText(f"Space to be freed: {total:.2f} MB")

    def delete_selected(self):
        for r in reversed(self.get_selected_rows()):
            full = self.table.item(r, 4).toolTip()
            try:
                os.remove(full)
                self.table.removeRow(r)
            except:
                pass
        self.update_space_label()

    def move_selected(self):
        dest = QFileDialog.getExistingDirectory(
            self, "Select Destination", os.path.expanduser("~/Downloads"), QFileDialog.ShowDirsOnly
        )
        if not dest:
            return
        for r in self.get_selected_rows():
            full = self.table.item(r, 4).toolTip()
            try:
                newp = shutil.move(full, dest)
                display = newp if len(newp) <= 60 else f"...{newp[-57:]}"
                item = self.table.item(r, 4)
                item.setText(display)
                item.setToolTip(newp)
            except:
                pass

    def archive_selected(self):
        default = os.path.expanduser(
            "~/Downloads/archive_%s.zip" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Archive As", default, "Zip Files (*.zip)"
        )
        if not save_path:
            return
        manifest = {}
        seen = set()
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for r in self.get_selected_rows():
                full = self.table.item(r, 4).toolTip()
                name = os.path.basename(full)
                arc  = name if name not in seen else f"{r}_{name}"
                seen.add(arc)
                zf.write(full, arc)
                manifest[arc] = full
                os.remove(full)
                self.table.item(r, 5).setText("Yes")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        self.update_space_label()
        self.status.setText(f"Archived to {save_path}")

    def reverse_archive(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "Select Archive to Reverse", os.path.expanduser("~/Downloads"), "Zip Files (*.zip)"
        )
        if not zip_path:
            return
        dest = os.path.dirname(zip_path)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(dest)
            QMessageBox.information(self, "Restore Complete", f"Files restored to {dest}")
        except Exception as e:
            QMessageBox.warning(self, "Restore Failed", str(e))

if __name__ == "__main__":
    print("[DEBUG] Application starting")
    app = QApplication(sys.argv)
    window = CleanupApp()
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec_())
