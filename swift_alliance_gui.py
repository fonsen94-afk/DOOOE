"""
PyQt5 GUI updated to import from swift_alliance package.
Run this file to launch the desktop GUI (requires PyQt5).
"""

import sys
import os
from decimal import Decimal
from PyQt5 import QtWidgets, QtCore, QtGui
from swift_alliance import create_bank_instance, generate_mt103, generate_pain001, payment_from_transaction
from swift_alliance import validate_pain001_generated, validate_mt103_text, SchemaNotFoundError
import tempfile
import smtplib

try:
    import paramiko
    HAS_PARAMIKO = True
except Exception:
    HAS_PARAMIKO = False

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
DEFAULT_LOGO_PATH = os.path.join(ASSETS_DIR, "swift_logo.svg")

class SwiftGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.bank = create_bank_instance()
        self.setWindowTitle("Swift Alliance - Message Converter & Validator")
        self.resize(980, 700)
        self.schema_path = None
        self.last_validation_result = {"valid": False, "errors": []}
        self._build_ui()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        top_h = QtWidgets.QHBoxLayout()
        main_layout.addLayout(top_h)

        acct_layout = QtWidgets.QHBoxLayout()
        top_h.addLayout(acct_layout)
        acct_layout.addWidget(QtWidgets.QLabel("Select Account:"))
        self.account_combo = QtWidgets.QComboBox()
        acct_layout.addWidget(self.account_combo)
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_accounts)
        acct_layout.addWidget(refresh_btn)
        self._load_accounts()

        logo_layout = QtWidgets.QVBoxLayout()
        top_h.addLayout(logo_layout)
        logo_layout.addStretch()
        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setFixedSize(220, 80)
        self.logo_label.setFrameShape(QtWidgets.QFrame.Box)
        self.logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_layout.addWidget(self.logo_label)
        load_logo_btn = QtWidgets.QPushButton("Load Logo")
        load_logo_btn.clicked.connect(self.on_load_logo)
        logo_layout.addWidget(load_logo_btn)
        logo_layout.addStretch()
        self._load_logo_preview(DEFAULT_LOGO_PATH)

        form = QtWidgets.QFormLayout()
        main_layout.addLayout(form)

        self.ordering_name = QtWidgets.QLineEdit()
        self.ordering_account = QtWidgets.QLineEdit()
        self.beneficiary_name = QtWidgets.QLineEdit()
        self.beneficiary_account = QtWidgets.QLineEdit()
        self.beneficiary_bic = QtWidgets.QLineEdit()
        self.amount_edit = QtWidgets.QLineEdit()
        self.currency_edit = QtWidgets.QLineEdit("USD")
        self.value_date = QtWidgets.QLineEdit()
        self.remittance = QtWidgets.QPlainTextEdit()
        self.reference_edit = QtWidgets.QLineEdit()

        form.addRow("Ordering Name:", self.ordering_name)
        form.addRow("Ordering Account (IBAN):", self.ordering_account)
        form.addRow("Beneficiary Name:", self.beneficiary_name)
        form.addRow("Beneficiary Account (IBAN):", self.beneficiary_account)
        form.addRow("Beneficiary BIC (optional):", self.beneficiary_bic)
        form.addRow("Amount:", self.amount_edit)
        form.addRow("Currency:", self.currency_edit)
        form.addRow("Value Date (YYYY-MM-DD):", self.value_date)
        form.addRow("Remittance Info:", self.remittance)
        form.addRow("Reference (optional):", self.reference_edit)

        opts_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(opts_layout)

        self.format_group = QtWidgets.QButtonGroup(self)
        rb_mt = QtWidgets.QRadioButton("MT103 (text)")
        rb_xml = QtWidgets.QRadioButton("ISO20022 pain.001 (XML)")
        rb_xml.setChecked(True)
        self.format_group.addButton(rb_mt, 0)
        self.format_group.addButton(rb_xml, 1)
        opts_layout.addWidget(QtWidgets.QLabel("Message Format:"))
        opts_layout.addWidget(rb_mt)
        opts_layout.addWidget(rb_xml)

        self.schema_label = QtWidgets.QLabel("No schema selected")
        self.schema_select_btn = QtWidgets.QPushButton("Select pain.001 XSD")
        self.schema_select_btn.clicked.connect(self.select_schema_file)
        opts_layout.addWidget(self.schema_label)
        opts_layout.addWidget(self.schema_select_btn)

        btn_row = QtWidgets.QHBoxLayout()
        main_layout.addLayout(btn_row)

        self.btn_generate = QtWidgets.QPushButton("Generate Preview")
        self.btn_generate.clicked.connect(self.on_generate)
        self.btn_validate = QtWidgets.QPushButton("Validate Now")
        self.btn_validate.clicked.connect(self.on_validate_clicked)
        self.btn_save = QtWidgets.QPushButton("Save Message")
        self.btn_save.clicked.connect(self.on_save)
        self.btn_send = QtWidgets.QPushButton("Send (mock)")
        self.btn_send.clicked.connect(self.on_send)

        btn_row.addWidget(self.btn_generate)
        btn_row.addWidget(self.btn_validate)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_send)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        main_layout.addWidget(splitter, stretch=1)

        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        splitter.addWidget(self.preview)

        val_widget = QtWidgets.QWidget()
        val_layout = QtWidgets.QVBoxLayout(val_widget)
        splitter.addWidget(val_widget)

        self.validation_status_label = QtWidgets.QLabel("Validation status: Not validated")
        self.validation_status_label.setStyleSheet("font-weight: bold;")
        val_layout.addWidget(self.validation_status_label)

        self.validation_list = QtWidgets.QPlainTextEdit()
        self.validation_list.setReadOnly(True)
        val_layout.addWidget(self.validation_list)

        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

        self.account_combo.currentIndexChanged.connect(self.on_account_changed)

    def _load_accounts(self):
        self.account_combo.clear()
        try:
            accounts = list(self.bank.accounts.values())
            if not accounts:
                self.account_combo.addItem("No accounts available", None)
                return
            for acc in accounts:
                label = f"{acc.account_number} — {acc.account_type.value} — {acc.balance:.2f} {acc.currency.value}"
                self.account_combo.addItem(label, acc.account_number)
        except Exception:
            self.account_combo.addItem("Error loading accounts", None)

    def on_account_changed(self, idx):
        acc_num = self.account_combo.currentData()
        if not acc_num:
            return
        try:
            acc = self.bank.accounts[acc_num]
            cust = self.bank.customers.get(acc.customer_id)
            if cust:
                self.ordering_name.setText(cust.first_name + " " + cust.last_name)
            self.ordering_account.setText(acc_num)
            self.currency_edit.setText(acc.currency.value)
        except Exception:
            pass

    def _collect_payment(self):
        try:
            amount = Decimal(self.amount_edit.text().strip())
        except Exception:
            raise ValueError("Invalid amount")
        payment = payment_from_transaction(
            account_number=self.ordering_account.text().strip(),
            account_name=self.ordering_name.text().strip(),
            beneficiary_account=self.beneficiary_account.text().strip(),
            beneficiary_name=self.beneficiary_name.text().strip(),
            amount=amount,
            currency=self.currency_edit.text().strip() or "USD",
            value_date=self.value_date.text().strip() or None,
            remittance_info=self.remittance.toPlainText().strip() or None,
            beneficiary_bic=self.beneficiary_bic.text().strip() or None,
            reference=self.reference_edit.text().strip() or None
        )
        return payment

    def on_generate(self):
        try:
            payment = self._collect_payment()
            fmt = self.format_group.checkedId()
            if fmt == 0:
                mt = generate_mt103(payment)
                self.preview.setPlainText(mt)
                valid, issues = validate_mt103_text(mt)
                self._set_validation_result(valid, issues)
                self.status.showMessage("MT103 preview generated and validated", 5000)
            else:
                xml = generate_pain001(payment)
                self.preview.setPlainText(xml)
                if self.schema_path:
                    valid, errors = validate_pain001_generated(xml, self.schema_path)
                    self._set_validation_result(valid, errors or [])
                    if valid:
                        self.status.showMessage("XML preview generated and validated (OK)", 5000)
                    else:
                        self.status.showMessage("XML preview generated (validation errors)", 8000)
                else:
                    self._set_validation_result(False, ["No pain.001 XSD selected. Please select an XSD to validate."])
                    self.status.showMessage("XML preview generated (no schema selected)", 5000)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_validate_clicked(self):
        content = self.preview.toPlainText()
        if not content:
            QtWidgets.QMessageBox.information(self, "Nothing to validate", "Generate a message first.")
            return
        fmt = self.format_group.checkedId()
        if fmt == 0:
            valid, issues = validate_mt103_text(content)
            self._set_validation_result(valid, issues)
            self.status.showMessage("MT103 validation completed", 5000)
        else:
            if not self.schema_path:
                QtWidgets.QMessageBox.warning(self, "Schema required", "Please select a pain.001 XSD to validate XML.")
                return
            try:
                valid, errors = validate_pain001_generated(content, self.schema_path)
                self._set_validation_result(valid, errors or [])
                self.status.showMessage("ISO20022 validation completed", 5000)
            except SchemaNotFoundError as e:
                QtWidgets.QMessageBox.critical(self, "Schema error", str(e))

    def _set_validation_result(self, valid: bool, errors):
        self.last_validation_result = {"valid": valid, "errors": errors or []}
        if valid:
            self.validation_status_label.setText("Validation status: VALID")
            self.validation_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.validation_list.setPlainText("No validation issues found.")
        else:
            self.validation_status_label.setText("Validation status: INVALID")
            self.validation_status_label.setStyleSheet("color: red; font-weight: bold;")
            text = ""
            if not errors:
                text = "Unknown validation failure."
            else:
                for i, e in enumerate(errors, 1):
                    text += f"{i}. {e}\n"
            self.validation_list.setPlainText(text)

    def on_save(self):
        content = self.preview.toPlainText()
        if not content:
            QtWidgets.QMessageBox.warning(self, "Nothing to save", "Generate a message first.")
            return
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Message", "", "All Files (*)")
        if fname:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
            self.status.showMessage(f"Saved to {fname}", 5000)

    def on_send(self):
        content = self.preview.toPlainText()
        if not content:
            QtWidgets.QMessageBox.warning(self, "Nothing to send", "Generate a message first.")
            return

        if not self.last_validation_result.get("valid", False):
            msg = "Message is not valid. Sending may be rejected by partners.\nDo you want to override and continue?"
            r = QtWidgets.QMessageBox.question(self, "Validation failed", msg, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if r != QtWidgets.QMessageBox.Yes:
                return

        options = ["Save to file (local)", "Send by email (SMTP)", "Upload by SFTP (optional)", "Mock log only"]
        item, ok = QtWidgets.QInputDialog.getItem(self, "Send message", "Choose send method:", options, 0, False)
        if not ok:
            return
        choice = item

        try:
            if choice == options[0]:
                fname, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Message for Sending", "", "All Files (*)")
                if fname:
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.status.showMessage(f"Saved to {fname}", 5000)
            elif choice == options[1]:
                self._send_via_smtp(content)
            elif choice == options[2]:
                self._send_via_sftp(content)
            else:
                logf = "swift_send_log.txt"
                with open(logf, "a", encoding="utf-8") as f:
                    f.write(f"----- {datetime.datetime.utcnow().isoformat()} -----\n")
                    f.write(content + "\n\n")
                QtWidgets.QMessageBox.information(self, "Mock Send", f"Logged to {logf}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Send error", str(e))

    def _send_via_smtp(self, content: str):
        host, ok1 = QtWidgets.QInputDialog.getText(self, "SMTP Server", "SMTP host (hostname:port):", text="smtp.example.com:587")
        if not ok1:
            return
        user, ok2 = QtWidgets.QInputDialog.getText(self, "SMTP User", "SMTP username:")
        if not ok2:
            return
        passwd, ok3 = QtWidgets.QInputDialog.getText(self, "SMTP Password (will not be stored)", "Password:", QtWidgets.QLineEdit.Password)
        if not ok3:
            return
        recipient, ok4 = QtWidgets.QInputDialog.getText(self, "Recipient", "Recipient email address:")
        if not ok4:
            return
        try:
            h, p = host.split(":")
            p = int(p)
            with smtplib.SMTP(h, p, timeout=10) as s:
                s.starttls()
                s.login(user, passwd)
                msg = f"Subject: SWIFT Message\n\n{content}"
                s.sendmail(user, [recipient], msg.encode("utf-8"))
            QtWidgets.QMessageBox.information(self, "Email Sent", "Message sent (SMTP).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "SMTP Error", f"Failed to send: {e}")

    def _send_via_sftp(self, content: str):
        if not HAS_PARAMIKO:
            QtWidgets.QMessageBox.warning(self, "Paramiko missing", "SFTP requires 'paramiko' package. Install via pip.")
            return
        host, ok1 = QtWidgets.QInputDialog.getText(self, "SFTP Host", "SFTP host (hostname):")
        if not ok1:
            return
        port_text, ok2 = QtWidgets.QInputDialog.getText(self, "SFTP Port", "SFTP port:", text="22")
        if not ok2:
            return
        user, ok3 = QtWidgets.QInputDialog.getText(self, "SFTP User", "SFTP username:")
        if not ok3:
            return
        passwd, ok4 = QtWidgets.QInputDialog.getText(self, "SFTP Password", "SFTP password (not stored):", QtWidgets.QLineEdit.Password)
        if not ok4:
            return
        remote_path, ok5 = QtWidgets.QInputDialog.getText(self, "Remote Path", "Remote path (full filename):", text="/upload/message.txt")
        if not ok5:
            return
        try:
            port = int(port_text)
            transport = paramiko.Transport((host, port))
            transport.connect(username=user, password=passwd)
            sftp = paramiko.SFTPClient.from_transport(transport)
            with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
                tf.write(content)
                tempname = tf.name
            sftp.put(tempname, remote_path)
            sftp.close()
            transport.close()
            os.unlink(tempname)
            QtWidgets.QMessageBox.information(self, "SFTP", "Uploaded successfully (SFTP).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "SFTP Error", f"Upload failed: {e}")

    def select_schema_file(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select pain.001 XSD", "", "XSD files (*.xsd);;All Files (*)")
        if fname:
            self.schema_path = fname
            self.schema_label.setText(os.path.basename(fname))
            self.status.showMessage(f"Schema set: {fname}", 5000)

    def on_load_logo(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select logo file (PNG or SVG)", "", "Images (*.png *.svg);;All Files (*)")
        if not fname:
            return
        try:
            os.makedirs(ASSETS_DIR, exist_ok=True)
            basename = os.path.basename(fname)
            dest = os.path.join(ASSETS_DIR, basename)
            with open(fname, "rb") as rf:
                data = rf.read()
            with open(dest, "wb") as wf:
                wf.write(data)
            self._load_logo_preview(dest)
            self.status.showMessage(f"Logo loaded to assets/{basename}", 5000)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Logo error", str(e))

    def _load_logo_preview(self, path: str):
        if not path or not os.path.exists(path):
            self.logo_label.setText("No logo")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".svg":
            svg_widget = QtSvgWidget(path, self.logo_label.size())
            pixmap = svg_widget.render_to_pixmap(self.logo_label.size())
            self.logo_label.setPixmap(pixmap)
        else:
            try:
                pixmap = QtGui.QPixmap(path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(self.logo_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    self.logo_label.setPixmap(pixmap)
                    return
            except Exception:
                pass
            self.logo_label.setText(os.path.basename(path))

class QtSvgWidget(QtWidgets.QWidget):
    def __init__(self, svg_path: str, size: QtCore.QSize):
        super().__init__()
        self.svg_path = svg_path
        try:
            from PyQt5.QtSvg import QSvgRenderer
        except Exception:
            QSvgRenderer = None
        self._renderer = QSvgRenderer(svg_path) if QSvgRenderer else None

    def render_to_pixmap(self, size: QtCore.QSize) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtCore.Qt.transparent)
        if self._renderer:
            painter = QtGui.QPainter(pixmap)
            self._renderer.render(painter)
            painter.end()
        return pixmap

def main():
    app = QtWidgets.QApplication(sys.argv)
    gui = SwiftGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()