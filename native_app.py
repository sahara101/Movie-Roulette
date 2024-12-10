import sys
import threading
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtGui import QDesktopServices
import movie_selector
import socketio
import requests
import time
import socket


class FlaskThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.socketio = movie_selector.socketio
        self.app = movie_selector.app
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Configure Socket.IO for async mode
        self.socketio.init_app(self.app, async_mode='threading', cors_allowed_origins='*')
        self.port_ready = threading.Event()  # Event to signal when the port is ready
        self.port = None  # To store the assigned port

    def run(self):
        try:
            # Use a socket to find an available port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))  # Bind to a free port
                self.port = s.getsockname()[1]  # Get the assigned port
                self.port_ready.set()  # Signal that the port is ready

            # Start the Flask server on the assigned port
            self.socketio.run(
                self.app,
                host='127.0.0.1',
                port=self.port,
                debug=False,
                use_reloader=False,
                allow_unsafe_werkzeug=True,
                log_output=True
            )
        except Exception as e:
            print(f"Error starting server: {e}")


class MovieRouletteApp(QMainWindow):
    def __init__(self, flask_thread):
        super().__init__()
        self.flask_thread = flask_thread
        self.setWindowTitle("Movie Roulette")

        # Wait for the Flask thread to retrieve the port
        if not flask_thread.port_ready.wait(timeout=5):
            print("Error: Flask server did not start in time.")
            sys.exit(1)  # Exit if the server fails to start
        flask_port = flask_thread.port

        # Get screen size and set window size to 80%
        screen = QApplication.primaryScreen().availableGeometry()
        width = int(screen.width() * 0.8)
        height = int(screen.height() * 0.8)

        # Set minimum size to prevent too small windows
        self.setMinimumSize(800, 600)

        # Set window size and center it
        self.resize(width, height)
        self.center()

        # Configure web profile
        profile = QWebEngineProfile.defaultProfile()
        settings = profile.settings()

        # Enable required features
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)

        # Create web view widget
        self.web = QWebEngineView()
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # Disable right-click menu

        # Set up new window handling
        self.web.page().profile().setHttpUserAgent('Mozilla/5.0')
        self.web.page().newWindowRequested.connect(self.handle_new_window)

        # Connect loadFinished signal to our handler
        self.web.loadFinished.connect(self.onPageLoadFinished)

        self.web.setUrl(QUrl(f"http://127.0.0.1:{flask_port}"))
        self.setCentralWidget(self.web)

        # Set up the menu bar
        self.create_menu_bar()

        # Initialize cache
        self.init_cache()

    def center(self):
        # Center window on screen
        qr = self.frameGeometry()
        cp = QApplication.primaryScreen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def update_trakt_button(self):
        self.web.page().runJavaScript("""
            // Update button state
            const button = document.querySelector('.trakt-connect-button');
            if (button) {
                button.className = 'trakt-connect-button connected';
                button.innerHTML = '<i class="fa-solid fa-plug-circle-xmark"></i> Disconnect from Trakt';
                button.disabled = false;
            }
        """)

    def onPageLoadFinished(self, ok):
        if ok:
            print("Page loaded successfully")
            # Inject native flag
            self.web.page().runJavaScript("""
                window.isNative = true;
                document.documentElement.classList.add('native-app');
            """)

    def handle_new_window(self, request):
        """Handle requests to open new windows/tabs"""
        url = request.requestedUrl()
        QDesktopServices.openUrl(url)

    def create_menu_bar(self):
        # File Menu
        file_menu = self.menuBar().addMenu('File')
        quit_action = QAction('Quit Movie Roulette', self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # View Menu
        view_menu = self.menuBar().addMenu('View')
        reload_action = QAction('Reload', self)
        reload_action.triggered.connect(self.web.reload)
        view_menu.addAction(reload_action)

        view_menu.addSeparator()

        # Add zoom actions
        zoom_in_action = QAction('Zoom In', self)
        zoom_in_action.triggered.connect(lambda: self.web.setZoomFactor(self.web.zoomFactor() + 0.1))
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction('Zoom Out', self)
        zoom_out_action.triggered.connect(lambda: self.web.setZoomFactor(self.web.zoomFactor() - 0.1))
        view_menu.addAction(zoom_out_action)

        reset_zoom_action = QAction('Reset Zoom', self)
        reset_zoom_action.triggered.connect(lambda: self.web.setZoomFactor(1.0))
        view_menu.addAction(reset_zoom_action)

        view_menu.addSeparator()

        # Move Window controls to View menu
        minimize_action = QAction('Minimize', self)
        minimize_action.triggered.connect(self.showMinimized)
        view_menu.addAction(minimize_action)

        zoom_window_action = QAction('Zoom', self)
        zoom_window_action.triggered.connect(lambda: self.setWindowState(self.windowState() ^ Qt.WindowState.WindowMaximized))
        view_menu.addAction(zoom_window_action)

        # Help Menu
        help_menu = self.menuBar().addMenu('Help')
        github_action = QAction('GitHub Repository', self)
        github_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/sahara101/Movie-Roulette')))
        help_menu.addAction(github_action)

        help_menu.addSeparator()

        donate_submenu = help_menu.addMenu('Donate')
        github_sponsor_action = QAction('GitHub Sponsor', self)
        github_sponsor_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/sponsors/sahara101')))
        donate_submenu.addAction(github_sponsor_action)

        kofi_action = QAction('Ko-fi', self)
        kofi_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl('https://ko-fi.com/sahara101/donate')))
        donate_submenu.addAction(kofi_action)

    def init_cache(self):
        try:
            requests.get(f'http://127.0.0.1:{self.flask_thread.port}/start_loading')
        except Exception as e:
            print(f"Error initializing cache: {e}")

    def closeEvent(self, event):
        print("Starting shutdown sequence...")
        self.web.close()
        try:
            requests.post(f'http://127.0.0.1:{self.flask_thread.port}/shutdown')
        except Exception as e:
            print("Error shutting down server:", e)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Movie Roulette")

    flask_thread = FlaskThread()
    flask_thread.daemon = True
    flask_thread.start()

    window = MovieRouletteApp(flask_thread)
    movie_selector.register_main_window(window)
    window.show()

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

