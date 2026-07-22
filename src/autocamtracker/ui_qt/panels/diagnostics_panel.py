from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class DiagnosticsPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        QVBoxLayout(self).addWidget(self.output)

    def set_health(self, items) -> None:
        self.output.setPlainText(
            "\n".join(
                f"{item.component}: {item.state.value.upper()} · {item.summary}"
                for item in items
            )
        )
