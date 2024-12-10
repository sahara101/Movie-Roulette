from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
import requests

class TraktAuthDialog(QDialog):
    def __init__(self, auth_url, main_window):
        super().__init__()
        self.main_window = main_window
        self.auth_url = auth_url 
        self.setWindowTitle("Trakt Authentication")
        self.setFixedSize(400, 500)
        
        # Set up the layout
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Title
        title = QLabel("Trakt Authentication")
        title.setFont(QFont('', 24, QFont.Weight.Bold))
        title.setStyleSheet("color: white;")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Instructions
        instructions = QLabel("1. Click the button below to open Trakt in your browser\n"
                            "2. Authorize Movie Roulette\n"
                            "3. Copy the authorization code\n"
                            "4. Paste it below and click Submit")
        instructions.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                qproperty-wordWrap: true;
            }
        """)
        layout.addWidget(instructions, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Auth button
        auth_button = QPushButton("Connect Trakt Account")
        auth_button.setStyleSheet("""
            QPushButton {
                background-color: #ED1C24;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 15px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF2D35;
            }
        """)
        auth_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(auth_url)))
        layout.addWidget(auth_button)
        
        # Code input
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Enter authorization code")
        self.code_input.setStyleSheet("""
            QLineEdit {
                background-color: #282A2D;
                color: white;
                border: 2px solid #ED1C24;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.code_input)
        
        # Submit button
        submit_button = QPushButton("Submit Code")
        submit_button.setStyleSheet("""
            QPushButton {
                background-color: #282A2D;
                color: white;
                border: 2px solid #ED1C24;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3A3C41;
            }
        """)
        submit_button.clicked.connect(self._submit_code)
        layout.addWidget(submit_button)
        
        # Set dialog style
        self.setLayout(layout)
        self.setStyleSheet("""
            QDialog {
                background-color: #3A3C41;
            }
        """)

    def _submit_code(self):
        code = self.code_input.text().strip()
        if code:
            try:
                print(f"Submitting code: {code}")
                response = requests.post('http://127.0.0.1:4000/trakt/token', 
                                      json={'code': code})
                print(f"Response status: {response.status_code}")
                print(f"Response text: {response.text}")
            
                if response.ok:
                    # Update button using the registered main window
                    from movie_selector import main_window
                    if main_window:
                        main_window.update_trakt_button()
                    self.accept()
                else:
                    print(f"Error response: {response.text}")
            except Exception as e:
                print(f"Error submitting code: {e}")
