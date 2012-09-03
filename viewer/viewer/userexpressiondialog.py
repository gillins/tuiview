
"""
Contains the UserExpressionDialog class
"""

from PyQt4.QtGui import QDialog, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt4.QtGui import QTextEdit, QPalette
from PyQt4.QtCore import SIGNAL, Qt

class UserExpressionDialog(QDialog):
    """
    Allows user to enter a expression and have it applied.
    Sends a signal with the expresson on Apply
    """
    def __init__(self, parent, col=None):
        QDialog.__init__(self, parent)
        # if this is not none col included in signal
        self.col = col 

        self.setWindowTitle("Enter Expression")

        self.exprEdit = QTextEdit(self)
        self.exprEdit.setAcceptRichText(False)

        self.hintEdit = QTextEdit(self)
        self.hintEdit.setText("""
Hint: Enter an expression using column names (ie 'col_a < 10'). 
Combine more complicated expressions with '&' and '|'.
For example '(a < 10) & (b > 1)'\n
Any other numpy expressions also valid - columns are represented as 
numpy arrays.
Use the special column 'row' for the row number.""")
        self.hintEdit.setReadOnly(True)
        # make background gray
        palette = self.hintEdit.palette()
        palette.setColor(QPalette.Base, Qt.lightGray)
        self.hintEdit.setPalette(palette)

        self.applyButton = QPushButton(self)
        self.applyButton.setText("Apply")

        self.closeButton = QPushButton(self)
        self.closeButton.setText("Close")

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.addWidget(self.applyButton)
        self.buttonLayout.addWidget(self.closeButton)

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.addWidget(self.exprEdit)
        self.mainLayout.addWidget(self.hintEdit)
        self.mainLayout.addLayout(self.buttonLayout)

        self.connect(self.closeButton, SIGNAL("clicked()"), self.close)
        self.connect(self.applyButton, SIGNAL("clicked()"), 
                                    self.applyExpression)

    def setHint(self, hint):
        "set the hint displayed"
        self.hintEdit.setText(hint)

    def applyExpression(self):
        "Sends a signal with the expression"
        expression = self.exprEdit.toPlainText()
        if self.col is None:
            self.emit(SIGNAL("newExpression(QString)"), expression)
        else:
            # include column
            self.emit(SIGNAL("newExpression(QString,int)"), 
                            expression, self.col)

