"""Small layout helpers shared by dock panels."""

from PySide6.QtWidgets import QFormLayout, QWidget


class FormPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
