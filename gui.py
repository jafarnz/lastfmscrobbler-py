import sys
import time
import io
import json
import os
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QListWidget, QListWidgetItem,
    QMessageBox, QProgressDialog, QGroupBox, QFormLayout, QRadioButton,
    QSpacerItem, QSizePolicy, QScrollArea, QFrame, QTextEdit, QDialog, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QBuffer, QIODevice, pyqtSlot, QUrl
from PyQt6.QtGui import QPixmap, QPalette, QColor, QCursor, QPainter, QFont
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtGui import QDesktopServices

# Import API functions and exception from main.py
from main import (
    get_session_key, search_track, get_album_tracks, scrobble_multiple_tracks,
    get_track_info, get_album_info, # Added get_album_info
    search_artist, get_artist_info, get_artist_top_tracks, get_artist_albums, # Added artist functions
    update_now_playing, # <<< Import new function
    LastfmApiError, API_KEY, API_SECRET, USERNAME, PASSWORD,
    get_auth_token, get_session_key_from_credentials,
)

# --- Constants ---
PLACEHOLDER_SIZE = 64
ARTIST_IMAGE_SIZE = 96
ALBUM_COVER_SIZE_MANUAL = 128
ALBUM_COVER_SIZE_ALBUM_TAB = 150

# --- Worker Thread for API Calls ---
# To prevent the GUI from freezing during network requests
class ApiWorker(QThread):
    # Signals to communicate back to the main GUI thread
    finished = pyqtSignal(object) # Can carry results or error info
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str) # current_count, total_count, message
    image_fetched = pyqtSignal(str, QPixmap) # url, pixmap - Signal for image fetching

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs
        self._is_interruption_requested = False # Flag for cancellation

    def run(self):
        try:
            # Add progress callback to kwargs if the task supports it
            if self.task == scrobble_multiple_tracks: # Use imported function name
                 # Define the callback function that emits the progress signal
                 def progress_callback(current, total, message):
                     # Check for interruption request before emitting progress
                     if self._is_interruption_requested:
                         # Optionally raise an exception or just stop emitting
                         # Raising an exception might be cleaner if the task can handle it
                         raise InterruptedError("Task cancelled by user")
                     self.progress.emit(current, total, message)
                 # Add it to the keyword arguments passed to the task
                 self.kwargs['progress_callback'] = progress_callback

            # Separate handling for image fetching task if we add one later
            # elif self.task == self.fetch_image_task:
            #     url = self.args[0]
            #     pixmap = self.fetch_image_task(url)
            #     if pixmap:
            #         self.image_fetched.emit(url, pixmap)
            #     # Handle image fetch errors if necessary
            #     return # Don't emit finished for image task

            result = self.task(*self.args, **self.kwargs)
            if not self._is_interruption_requested: # Only emit finished if not cancelled
                self.finished.emit(result)
        except InterruptedError:
             print("Task execution interrupted.") # Or handle more gracefully
             # Don't emit finished or error signal if interrupted cleanly
        except LastfmApiError as e: # Use imported exception name
            if not self._is_interruption_requested:
                self.error.emit(f"API Error ({e.code}): {e.message}")
        except Exception as e:
             if not self._is_interruption_requested:
                self.error.emit(f"An unexpected error occurred: {e}")

    def requestInterruption(self):
        self._is_interruption_requested = True
        super().requestInterruption() # Call base class method too


# --- Login Dialog ---
class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Last.fm Login")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # API Key and Secret fields
        api_group = QGroupBox("Last.fm API Credentials")
        api_form = QFormLayout()
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter your Last.fm API Key")
        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("Enter your Last.fm API Secret")
        
        api_form.addRow("API Key:", self.api_key_input)
        api_form.addRow("API Secret:", self.api_secret_input)
        api_group.setLayout(api_form)
        layout.addWidget(api_group)
        
        # Username and Password fields
        auth_group = QGroupBox("Last.fm Account")
        auth_form = QFormLayout()
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your Last.fm username")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your Last.fm password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        auth_form.addRow("Username:", self.username_input)
        auth_form.addRow("Password:", self.password_input)
        auth_group.setLayout(auth_form)
        layout.addWidget(auth_group)
        
        # Help text
        help_text = QLabel(
            "To get your API credentials:\n"
            "1. Go to https://www.last.fm/api/account/create\n"
            "2. Create a new API account\n"
            "3. Copy the API Key and Secret\n"
            "4. Enter your Last.fm username and password"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #AAAAAA; font-size: 9pt;")
        layout.addWidget(help_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.login_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        
        # Load saved credentials if they exist
        self.load_saved_credentials()
    
    def load_saved_credentials(self):
        """Load saved credentials from the config file."""
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r') as f:
                    config = json.load(f)
                    # Always load if file exists, no 'remember_credentials' check needed
                    self.api_key_input.setText(config.get('api_key', ''))
                    self.api_secret_input.setText(config.get('api_secret', ''))
                    self.username_input.setText(config.get('username', ''))
                    self.password_input.setText(config.get('password', ''))
        except Exception as e:
            print(f"Error loading saved credentials: {e}")
    
    def save_credentials(self):
        """Save credentials to the config file."""
        # Always save credentials now
        config = {
            'api_key': self.api_key_input.text().strip(),
            'api_secret': self.api_secret_input.text().strip(),
            'username': self.username_input.text().strip(),
            'password': self.password_input.text().strip(),
            # No 'remember_credentials' field needed anymore
        }
        try:
            with open('config.json', 'w') as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Error saving credentials: {e}")
        # No else block needed to remove config.json, as we always save
    
    def get_credentials(self):
        return {
            'api_key': self.api_key_input.text().strip(),
            'api_secret': self.api_secret_input.text().strip(),
            'username': self.username_input.text().strip(),
            'password': self.password_input.text().strip()
        }

# --- Main Application Window ---
class LastfmScrobblerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.session_key = None
        self.api_worker = None
        self.progress_dialog = None
        self.current_album_artist = None
        self.current_album_name = None
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self.handle_image_reply)
        self.image_cache = {}
        self.image_widget_map = {}
        self.selected_search_item_widget = None
        self.pending_replies = set()
        
        # Initialize UI first
        self.init_ui()
        
        # Then show login dialog
        self.show_login_dialog()
    
    def show_login_dialog(self):
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            credentials = dialog.get_credentials()
            if not all(credentials.values()):
                QMessageBox.critical(self, "Error", "Please fill in all fields.")
                sys.exit(1)
            
            # Save credentials if remember is checked
            dialog.save_credentials()
            
            # Update the API credentials in main.py
            import main
            main.API_KEY = credentials['api_key']
            main.API_SECRET = credentials['api_secret']
            main.USERNAME = credentials['username']
            main.PASSWORD = credentials['password']
            
            # Try to authenticate
            self.authenticate()
        else:
            sys.exit(0)  # Exit if login was cancelled

    def init_ui(self):
        self.setWindowTitle('✧･ﾟ: *✧･ﾟ cunty scrobbler ･ﾟ✧*:･ﾟ✧') # Fierce new title
        self.setGeometry(100, 100, 800, 650) # Even larger size

        # Initialize search timer for dynamic searches
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.trigger_dynamic_search)
        
        self.main_layout = QVBoxLayout(self)

        # Status Label (for auth status, errors, etc.)
        self.status_label = QLabel("Status: Initializing...")
        self.status_label.setObjectName("status_label") # Assign object name for styling
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.status_label)

        # --- Tabs for different functions ---
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # -- Scrobble Tab --
        self._setup_scrobble_tab()
        self._setup_search_tab()
        self._setup_album_tab()

        # --- Set Search & Scrobble as default tab ---
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Search & Scrobble":
                self.tabs.setCurrentIndex(i)
                break
        # -------------------------------------------

        # --- Auth Button --- #
        self.auth_button = QPushButton("Authenticate")
        self.auth_button.clicked.connect(self.authenticate)
        self.main_layout.addWidget(self.auth_button)

        self.status_label.setText("Status: Not Authenticated") # Set initial status after UI init
        self.status_label.setStyleSheet("color: #ff4d94; background-color: #fff0f5; padding: 6px; border-radius: 8px; border: 1px solid #ff85a2;") # Pink theme

    def _setup_scrobble_tab(self):
        # -- Scrobble Tab --
        self.scrobble_tab = QWidget()
        self.tabs.addTab(self.scrobble_tab, "Manual Scrobble")
        self.scrobble_layout = QHBoxLayout(self.scrobble_tab)

        # Left side: Form
        # ... (form setup as before) ...
        scrobble_form_widget = QWidget()
        scrobble_form_layout_main = QVBoxLayout(scrobble_form_widget)
        scrobble_input_group = QGroupBox("Track Details")
        scrobble_form_layout = QFormLayout()

        self.artist_input = QLineEdit()
        self.artist_input.setPlaceholderText("Required")
        self.track_input = QLineEdit()
        self.track_input.setPlaceholderText("Required")
        self.album_input = QLineEdit()
        self.album_input.setPlaceholderText("Optional")
        self.count_input = QSpinBox()
        self.count_input.setRange(1, 2800)
        self.count_input.setValue(1)
        self.count_input.setToolTip("How many times to scrobble this specific track.")

        scrobble_form_layout.addRow("Artist:", self.artist_input)
        scrobble_form_layout.addRow("Track:", self.track_input)
        scrobble_form_layout.addRow("Album:", self.album_input)
        scrobble_form_layout.addRow("Scrobble Count:", self.count_input)

        self.fetch_manual_album_info_button = QPushButton("Fetch Album Info")
        self.fetch_manual_album_info_button.setToolTip("Fetch album cover and details based on Artist/Album fields")
        self.fetch_manual_album_info_button.clicked.connect(self.fetch_album_info_for_manual_scrobble)
        self.fetch_manual_album_info_button.setEnabled(False)
        scrobble_form_layout.addRow(self.fetch_manual_album_info_button)

        # --- Add 'Update Now Playing' checkbox here ---
        self.now_playing_checkbox = QCheckBox("✨ Update 'Now Playing' status?")
        self.now_playing_checkbox.setChecked(True) # Default to checked
        self.now_playing_checkbox.setToolTip("If checked, Last.fm will show this track as 'Now Playing' before scrobbling.")
        scrobble_form_layout.addRow(self.now_playing_checkbox)
        # -------------------------------------------

        scrobble_input_group.setLayout(scrobble_form_layout)
        scrobble_form_layout_main.addWidget(scrobble_input_group)

        self.scrobble_button = QPushButton("Scrobble Track(s)")
        self.scrobble_button.setEnabled(False)
        self.scrobble_button.clicked.connect(self.start_scrobble_task)
        scrobble_form_layout_main.addWidget(self.scrobble_button, alignment=Qt.AlignmentFlag.AlignTop)
        scrobble_form_layout_main.addStretch(1)

        self.scrobble_layout.addWidget(scrobble_form_widget, 2)

        # Right side: Album Cover Preview
        # ... (preview setup as before) ...
        scrobble_preview_widget = QWidget()
        scrobble_preview_layout = QVBoxLayout(scrobble_preview_widget)
        scrobble_preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
        self.manual_album_cover_label = QLabel("Album cover preview")
        self.manual_album_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.manual_album_cover_label.setFixedSize(ALBUM_COVER_SIZE_MANUAL, ALBUM_COVER_SIZE_MANUAL)
        self.manual_album_cover_label.setStyleSheet("border: 1px dashed #666; background-color: #383838;")
        self.manual_album_cover_label.setToolTip("Album cover art will be shown here after fetching.")
        scrobble_preview_layout.addWidget(self.manual_album_cover_label)
        scrobble_preview_layout.addStretch(1)
        self.scrobble_layout.addWidget(scrobble_preview_widget, 1)

    def _setup_search_tab(self):
        # -- Search Tab --
        self.search_tab = QWidget()
        self.tabs.addTab(self.search_tab, "Search & Scrobble")
        self.search_layout = QVBoxLayout(self.search_tab)

        # Search Input Group
        # ... (input setup as before) ...
        search_input_group = QGroupBox("Search Last.fm")
        search_form_layout = QFormLayout()
        self.search_artist_input = QLineEdit()
        self.search_artist_input.setPlaceholderText("Enter artist name (required for search)")
        self.search_artist_input.textChanged.connect(self.on_search_text_changed)
        self.search_track_input = QLineEdit()
        self.search_track_input.setPlaceholderText("Enter track name (optional - searches tracks)")
        self.search_track_input.textChanged.connect(self.on_search_text_changed)
        search_form_layout.addRow("Artist:", self.search_artist_input)
        search_form_layout.addRow("Track:", self.search_track_input)
        search_input_group.setLayout(search_form_layout)
        self.search_layout.addWidget(search_input_group)

        # Search Results Group (Corrected Layout)
        search_results_group = QGroupBox("Search Results")
        search_results_group_layout = QVBoxLayout(search_results_group) # Layout for the groupbox

        self.search_results_scroll_area = QScrollArea()
        self.search_results_scroll_area.setWidgetResizable(True)
        self.search_results_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_results_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.search_results_scroll_area.setObjectName("search_results_scroll")

        # Widget and Layout *inside* the scroll area
        self.search_results_widget = QWidget()
        self.search_results_widget.setObjectName("search_results_widget")
        self.search_results_layout = QVBoxLayout(self.search_results_widget) # Set layout ON the widget
        self.search_results_layout.setContentsMargins(5, 5, 5, 5)
        self.search_results_layout.setSpacing(6)
        self.search_results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.search_results_scroll_area.setWidget(self.search_results_widget)

        # Add ScrollArea to the GroupBox layout
        search_results_group_layout.addWidget(self.search_results_scroll_area)

        # Scrobble controls (Now added correctly to the GroupBox layout below scroll area)
        search_scrobble_layout = QHBoxLayout()
        search_scrobble_layout.addWidget(QLabel("Scrobble Count:"))
        self.search_count_input = QSpinBox()
        self.search_count_input.setRange(1, 2800) # <<< Updated Max Value
        self.search_count_input.setValue(1)
        search_scrobble_layout.addWidget(self.search_count_input)
        self.search_scrobble_button = QPushButton("Scrobble Selected Track")
        self.search_scrobble_button.setEnabled(False)
        self.search_scrobble_button.clicked.connect(self.scrobble_selected_search_result)
        search_scrobble_layout.addWidget(self.search_scrobble_button)
        search_scrobble_layout.addStretch() # Push controls left

        # Add scrobble controls layout to the GroupBox layout
        search_results_group_layout.addLayout(search_scrobble_layout)

        # Add the GroupBox to the main search tab layout
        self.search_layout.addWidget(search_results_group)

    def _setup_album_tab(self):
         # -- Album Scrobble Tab --
        self.album_tab = QWidget()
        self.tabs.addTab(self.album_tab, "Album Scrobble")
        self.album_layout = QVBoxLayout(self.album_tab)

        # Top section: Input and Album Info
        top_album_section_layout = QHBoxLayout()

        # Album Input Group (Corrected Setup)
        album_input_group = QGroupBox("Album Details")
        album_form_layout = QFormLayout() # Create the form layout

        self.album_artist_input = QLineEdit()
        self.album_artist_input.setPlaceholderText("Artist Name")
        self.album_name_input = QLineEdit()
        self.album_name_input.setPlaceholderText("Album Title")

        # Add widgets to the form layout
        album_form_layout.addRow("Artist:", self.album_artist_input)
        album_form_layout.addRow("Album:", self.album_name_input)
        album_input_group.setLayout(album_form_layout) # Set layout on the group box

        self.fetch_tracks_button = QPushButton("Fetch Album Info")
        self.fetch_tracks_button.setToolTip("Fetch album tracks and cover art")
        self.fetch_tracks_button.clicked.connect(self.start_fetch_album_info_task)
        # fetch button should probably be enabled when authenticated
        # self.fetch_tracks_button.setEnabled(False)

        # Layout for Input Group + Button
        input_v_layout = QVBoxLayout()
        input_v_layout.addWidget(album_input_group)
        input_v_layout.addWidget(self.fetch_tracks_button)
        input_v_layout.addStretch()
        top_album_section_layout.addLayout(input_v_layout, 1)

        # Album Cover/Info Display
        album_display_group = QGroupBox("Fetched Album Info")
        album_display_layout = QVBoxLayout(album_display_group)
        album_display_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.album_cover_label = QLabel("Album cover will appear here.")
        self.album_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_cover_label.setFixedSize(ALBUM_COVER_SIZE_ALBUM_TAB, ALBUM_COVER_SIZE_ALBUM_TAB)
        self.album_cover_label.setStyleSheet("border: 1px dashed #666; background-color: #383838;")
        album_display_layout.addWidget(self.album_cover_label)

        self.album_info_label = QLabel("Album details...")
        self.album_info_label.setWordWrap(True)
        self.album_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        album_display_layout.addWidget(self.album_info_label)
        album_display_layout.addStretch()
        top_album_section_layout.addWidget(album_display_group, 1)

        self.album_layout.addLayout(top_album_section_layout)

        # Bottom section: Fetched Tracks List and Controls
        album_tracks_group = QGroupBox("Fetched Tracks")
        album_tracks_outer_layout = QVBoxLayout(album_tracks_group)

        # Scroll Area setup
        self.album_tracks_scroll_area = QScrollArea()
        self.album_tracks_scroll_area.setWidgetResizable(True)
        self.album_tracks_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.album_tracks_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.album_tracks_widget = QWidget()
        self.album_tracks_widget.setObjectName("album_tracks_widget")
        self.album_tracks_layout = QVBoxLayout(self.album_tracks_widget)
        self.album_tracks_layout.setContentsMargins(5,5,5,5)
        self.album_tracks_layout.setSpacing(4)
        self.album_tracks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.album_tracks_scroll_area.setWidget(self.album_tracks_widget)
        album_tracks_outer_layout.addWidget(self.album_tracks_scroll_area)

        # Controls layout setup
        album_scrobble_layout = QHBoxLayout()
        album_scrobble_layout.addWidget(QLabel("Scrobbles per Track:"))
        self.album_count_input = QSpinBox()
        self.album_count_input.setRange(1, 2800) # <<< Updated Max Value
        self.album_count_input.setValue(1)
        self.album_count_input.setToolTip("How many times EACH track in the list will be scrobled.")
        album_scrobble_layout.addWidget(self.album_count_input)
        self.scrobble_album_button = QPushButton("Scrobble Entire Album")
        # self.scrobble_album_button.setEnabled(False)
        self.scrobble_album_button.clicked.connect(self.start_scrobble_album_task)
        album_scrobble_layout.addWidget(self.scrobble_album_button)
        album_tracks_outer_layout.addLayout(album_scrobble_layout)

        self.album_layout.addWidget(album_tracks_group)

    # --- Image Handling --- Helper functions
    def request_image(self, url, target_label):
        """Requests an image download for the given URL and target QLabel."""
        if not url:
            # Set default/placeholder image if no URL
            target_label.setPixmap(self.get_placeholder_pixmap(target_label.sizeHint(), "No Image"))
            return

        if url in self.image_cache:
            pixmap = self.image_cache[url]
            self.set_scaled_pixmap(target_label, pixmap)
        else:
            target_label.setPixmap(self.get_placeholder_pixmap(target_label.sizeHint(), "Loading..."))
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "LastfmScrobblerDeluxe/1.0")
            reply = self.network_manager.get(request)
            # Store the target label AND add reply to pending set
            self.image_widget_map[url] = target_label
            self.pending_replies.add(reply)

    def handle_image_reply(self, reply: QNetworkReply):
        """Handles the finished network reply for an image request."""
        # Remove reply from pending set regardless of outcome
        self.pending_replies.discard(reply)

        url = reply.url().toString()
        target_label = self.image_widget_map.pop(url, None)

        if not target_label:
            reply.deleteLater()
            return

        if reply.error() == QNetworkReply.NetworkError.NoError:
            image_data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data):
                self.image_cache[url] = pixmap
                self.set_scaled_pixmap(target_label, pixmap)
            else:
                print(f"Error: Could not load image data from {url}")
                target_label.setPixmap(self.get_placeholder_pixmap(target_label.sizeHint(), "Load Error"))
        elif reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
             print(f"Image request cancelled for {url}")
             # Optionally set a specific "Cancelled" placeholder
             target_label.setPixmap(self.get_placeholder_pixmap(target_label.sizeHint(), "Cancelled"))
        else:
            error_string = reply.errorString()
            print(f"Network Error ({reply.error()}): {error_string} for URL {url}")
            placeholder_text = f"Net Error"
            if reply.error() == QNetworkReply.NetworkError.ContentNotFoundError:
                 placeholder_text = "Not Found"
            target_label.setPixmap(self.get_placeholder_pixmap(target_label.sizeHint(), placeholder_text))

        reply.deleteLater()

    def set_scaled_pixmap(self, label, pixmap):
        """Scales and sets a pixmap on a label, keeping aspect ratio."""
        if not pixmap or pixmap.isNull():
            label.setPixmap(self.get_placeholder_pixmap(label.sizeHint(), "Invalid"))
            return
        scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled_pixmap)

    def get_placeholder_pixmap(self, size, text=None):
        """Creates a stylish placeholder pixmap with optional text."""
        pixmap = QPixmap(size)
        if pixmap.isNull(): # Handle case where size might be invalid initially
             pixmap = QPixmap(QSize(64, 64)) # Default fallback size
        pixmap.fill(QColor('#ffb6d9')) # Cute pink background

        if text:
            painter = QPainter(pixmap)
            painter.setPen(QColor('#ffffff')) # White text
            # Adjust font size based on pixmap size
            font_size = max(8, min(size.width() // len(text) if len(text) > 0 else 10, size.height() // 3))
            font = QFont()
            font.setPointSize(font_size)
            font.setBold(True) # Make text bold
            painter.setFont(font)
            # Draw text centered
            text_rect = pixmap.rect()
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.end()

        return pixmap

    # --- Authentication Logic ---
    def authenticate(self):
        self.status_label.setText("Status: Authenticating...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during auth
        
        # Use the direct credential-based authentication
        self.api_worker = ApiWorker(get_session_key_from_credentials)
        self.api_worker.finished.connect(self.auth_finished)
        self.api_worker.error.connect(self.auth_error)
        self.api_worker.start()

    def auth_finished(self, session_key):
        if session_key:
            self.session_key = session_key
            self.status_label.setText("Status: Authenticated Successfully")
            self.status_label.setStyleSheet("color: #ff4d94; background-color: #fff0f5; padding: 6px; border-radius: 8px; border: 1px solid #ff85a2;")
            self.set_controls_enabled(True)
            self.auth_button.setText("Authenticated")
            self.auth_button.setEnabled(False)
            # --- Explicitly enable Album Fetch button --- #
            self.fetch_tracks_button.setEnabled(True)
            self.fetch_manual_album_info_button.setEnabled(True)
            # ------------------------------------------ #
        else:
            self.status_label.setText("Status: Authentication Failed (Unknown Reason)")
            self.status_label.setStyleSheet("color: #cc0066; background-color: #fff0f5; padding: 6px; border-radius: 8px; border: 1px solid #ff4d94;")
            self.set_controls_enabled(True) # Keep controls enabled on fail, but auth button changes
            self.auth_button.setText("Re-authenticate")
            self.auth_button.setEnabled(True)
            QMessageBox.critical(self, "Authentication Error", "Failed to get session key.")
        self.api_worker = None

    def auth_error(self, error_message):
        self.session_key = None
        self.status_label.setText("Status: Authentication Failed!")
        self.status_label.setStyleSheet("color: #cc0066; background-color: #fff0f5; padding: 6px; border-radius: 8px; border: 1px solid #ff4d94;")
        self.set_controls_enabled(True) # Keep controls enabled on fail
        self.auth_button.setText("Re-authenticate")
        self.auth_button.setEnabled(True)
        self.api_worker = None
        QMessageBox.critical(self, "Authentication Error", error_message)


    # --- Search Logic ---
    def start_search_task(self):
        # This function might be redundant now with dynamic search, but keep for potential future use
        artist = self.search_artist_input.text().strip()
        track = self.search_track_input.text().strip()

        if not artist:
            QMessageBox.warning(self, "Input Missing", "Please enter an Artist name for search.")
            return

        # Re-use trigger_dynamic_search logic
        self.trigger_dynamic_search()
        # self.status_label.setText(f"Status: Searching...")
        # self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        # self.set_controls_enabled(False)
        # self._clear_search_results_layout()
        # self.search_scrobble_button.setEnabled(False)

        # # Determine search type
        # if track:
        #     self.api_worker = ApiWorker(search_track, artist, track)
        #     self.api_worker.finished.connect(self.search_tracks_finished)
        # else:
        #     self.api_worker = ApiWorker(search_artist, artist)
        #     self.api_worker.finished.connect(self.search_artists_finished)

        # self.api_worker.error.connect(self.search_error)
        # self.api_worker.start()


    def search_tracks_finished(self, results):
        """Handles results from track.search API call."""
        self.set_controls_enabled(True)
        self._clear_search_results_layout()
        self.selected_search_item_widget = None
        self.search_scrobble_button.setEnabled(False)

        if not results:
            self.status_label.setText("Status: Track search returned no results.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.search_results_layout.addWidget(QLabel("No tracks found."))
        else:
            self.status_label.setText(f"Status: Found {len(results)} track(s). Click to select, double-click to populate scrobble form.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            for track_data in results:
                item_widget = self.create_track_result_item(track_data)
                self.search_results_layout.addWidget(item_widget)

        self.api_worker = None

    def search_artists_finished(self, results):
        """Handles results from artist.search API call."""
        self.set_controls_enabled(True)
        self._clear_search_results_layout()
        self.selected_search_item_widget = None
        self.search_scrobble_button.setEnabled(False) # Can't scrobble an artist directly

        if not results:
            self.status_label.setText("Status: Artist search returned no results.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.search_results_layout.addWidget(QLabel("No artists found."))
        else:
            self.status_label.setText(f"Status: Found {len(results)} artist(s). Click to select, double-click to view details.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            for artist_data in results:
                item_widget = self.create_artist_result_item(artist_data) # Use the implemented function
                self.search_results_layout.addWidget(item_widget)

        self.api_worker = None

    def create_track_result_item(self, track_data):
        """Creates a QFrame widget representing a single track search result."""
        item_frame = QFrame()
        item_frame.setObjectName("search_result_item") # For styling
        item_frame.setFrameShape(QFrame.Shape.StyledPanel)
        item_frame.setLineWidth(1)
        item_frame.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)) # Make it look clickable
        item_frame.setProperty("item_type", "track") # Identify item type
        item_frame.setProperty("track_data", track_data) # Store data
        item_frame.setProperty("selected", False)
        # Use stylesheet

        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(5, 5, 5, 5)
        item_layout.setSpacing(10)

        # Image Label
        image_label = QLabel()
        image_size = PLACEHOLDER_SIZE # Use constant
        image_label.setFixedSize(image_size, image_size)
        image_label.setStyleSheet("border: none; border-radius: 4px;") # Rounded corners for image too
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.request_image(track_data.get('image_url'), image_label)
        item_layout.addWidget(image_label)

        # Text Labels Layout
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        track_name = track_data.get('name', 'N/A')
        artist_name = track_data.get('artist', 'N/A')

        track_label = QLabel(f"<b>{track_name}</b>")
        track_label.setToolTip(track_name)
        # Style via QSS
        artist_label = QLabel(artist_name)
        artist_label.setObjectName("artist_label") # For specific styling
        artist_label.setToolTip(artist_name)
        # Style via QSS

        text_layout.addWidget(track_label)
        text_layout.addWidget(artist_label)
        text_layout.addStretch()

        item_layout.addLayout(text_layout)
        item_layout.addStretch() # Push content left

        listeners = track_data.get('listeners')
        if listeners:
            listeners_label = QLabel(f"{int(listeners):,} listeners")
            listeners_label.setStyleSheet("color: #999999; font-size: 8pt; border: none; background: transparent;")
            listeners_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
            item_layout.addWidget(listeners_label)

        # Connect signals (using mousePressEvent for simplicity)
        item_frame.mousePressEvent = partial(self.on_search_item_clicked, item_frame)
        item_frame.mouseDoubleClickEvent = partial(self.on_search_item_double_clicked, item_frame)

        return item_frame

    def create_artist_result_item(self, artist_data):
        """Creates a QFrame widget representing a single artist search result."""
        item_frame = QFrame()
        item_frame.setObjectName("search_result_item") # Use same object name for styling
        item_frame.setFrameShape(QFrame.Shape.StyledPanel)
        item_frame.setLineWidth(1)
        item_frame.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        item_frame.setProperty("item_type", "artist") # Identify item type
        item_frame.setProperty("artist_data", artist_data)
        item_frame.setProperty("selected", False)

        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(8, 8, 8, 8) # Slightly more padding for artists
        item_layout.setSpacing(12)

        # Artist Image
        image_label = QLabel()
        image_size = ARTIST_IMAGE_SIZE
        image_label.setFixedSize(image_size, image_size)
        image_label.setStyleSheet("border: none; border-radius: 4px;")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.request_image(artist_data.get('image_url'), image_label)
        item_layout.addWidget(image_label)

        # Artist Name and Listeners
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        artist_name = artist_data.get('name', 'N/A')
        artist_label_widget = QLabel(f"<b>{artist_name}</b>") # Assign to variable
        artist_label_widget.setToolTip(artist_name)
        artist_label_widget.setStyleSheet("font-size: 12pt; border: none; background: transparent;") # Larger font, ensure no border/bg

        listeners = artist_data.get('listeners')
        listeners_label = QLabel(f"{int(listeners):,} listeners" if listeners else "Listeners: N/A")
        listeners_label.setObjectName("artist_label") # Dimmer text (uses existing style)
        listeners_label.setStyleSheet("border: none; background: transparent;") # Ensure no border/bg


        text_layout.addWidget(artist_label_widget)
        text_layout.addWidget(listeners_label)
        text_layout.addStretch()

        item_layout.addLayout(text_layout)
        item_layout.addStretch()

        # Connect signals
        item_frame.mousePressEvent = partial(self.on_search_item_clicked, item_frame)
        item_frame.mouseDoubleClickEvent = partial(self.on_artist_item_double_clicked, item_frame)

        return item_frame

    def on_search_item_clicked(self, item_widget, event):
        """Handles single clicks on search result items.
           Selects the item visually and populates the search input fields.
        """
        # Deselect previously selected item
        if self.selected_search_item_widget and self.selected_search_item_widget != item_widget:
             # ... (deselection logic as before) ...
             try:
                 self.selected_search_item_widget.setProperty("selected", False)
                 self.selected_search_item_widget.setStyleSheet(self.selected_search_item_widget.styleSheet())
             except RuntimeError:
                 pass

        # Select new item visually
        item_widget.setProperty("selected", True)
        item_widget.setStyleSheet(item_widget.styleSheet())
        self.selected_search_item_widget = item_widget

        item_type = item_widget.property("item_type")

        # --- Populate Search Fields --- #
        if item_type == "artist":
            artist_data = item_widget.property("artist_data")
            if artist_data:
                artist_name = artist_data.get("name")
                if artist_name:
                    print(f"Artist '{artist_name}' clicked, populating search fields.")
                    # Block signals temporarily to prevent immediate re-search trigger
                    self.search_artist_input.blockSignals(True)
                    self.search_track_input.blockSignals(True)

                    self.search_artist_input.setText(artist_name)
                    self.search_track_input.clear() # Clear track field when artist clicked

                    self.search_artist_input.blockSignals(False)
                    self.search_track_input.blockSignals(False)
                    # Optionally trigger search timer or focus track input?
                    # self.search_track_input.setFocus()
                    # self.on_search_text_changed() # Manually trigger timer
            # Keep scrobble button disabled for artist selection
            self.search_scrobble_button.setEnabled(False)

        elif item_type == "track":
            track_data = item_widget.property("track_data")
            if track_data:
                artist_name = track_data.get("artist")
                track_name = track_data.get("name")
                if artist_name and track_name:
                    print(f"Track '{track_name}' clicked, populating search fields.")
                    # Block signals temporarily
                    self.search_artist_input.blockSignals(True)
                    self.search_track_input.blockSignals(True)

                    self.search_artist_input.setText(artist_name)
                    self.search_track_input.setText(track_name)

                    self.search_artist_input.blockSignals(False)
                    self.search_track_input.blockSignals(False)
                    # Optionally trigger search?
                    # self.on_search_text_changed() # Manually trigger timer

            # Enable scrobble button only if authenticated and a TRACK item is selected
            self.search_scrobble_button.setEnabled(bool(self.session_key))
        else:
            # Unknown item type, disable scrobble button
             self.search_scrobble_button.setEnabled(False)

    def on_search_item_double_clicked(self, item_widget, event):
        """Handles double clicks to populate the scrobble tab (for tracks) or show artist details."""
        item_type = item_widget.property("item_type")
        if item_type == "track":
            track_data = item_widget.property("track_data")
            self.populate_scrobble_from_search(track_data)
        elif item_type == "artist":
            self.on_artist_item_double_clicked(item_widget, event)

    def on_artist_item_double_clicked(self, item_widget, event):
        """Handles double click on an artist item - show details in the search results area."""
        artist_data = item_widget.property("artist_data")
        if artist_data:
            artist_name = artist_data.get("name")
            print(f"Double clicked artist: {artist_name} - fetching details...")
            self.fetch_and_display_artist_details(artist_name)

    def fetch_and_display_artist_details(self, artist_name):
        """Fetches detailed artist info via get_artist_info and shows it in the search results area."""
        self.status_label.setText(f"Status: Fetching details for artist '{artist_name}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False)
        # Clear current results and show loading indicator
        self._clear_search_results_layout()
        loading_label = QLabel(f"Loading details for {artist_name}...")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.search_results_layout.addWidget(loading_label)

        # Use worker thread
        self.api_worker = ApiWorker(get_artist_info, artist_name)
        self.api_worker.finished.connect(self.artist_info_finished)
        self.api_worker.error.connect(self.search_error) # Reuse search error handler for now
        self.api_worker.start()

    def artist_info_finished(self, artist_info):
        """Displays detailed artist information in the search tab results area."""
        self.set_controls_enabled(True)
        self._clear_search_results_layout()

        if not artist_info:
            self.status_label.setText("Status: Failed to load artist details.")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            error_label = QLabel("Could not load artist details.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.search_results_layout.addWidget(error_label)
        else:
            artist_name = artist_info.get('name', 'N/A')
            self.status_label.setText(f"Status: Displaying details for {artist_name}.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")

            # Create a widget to display artist info
            artist_detail_widget = self.create_artist_detail_view(artist_info)
            self.search_results_layout.addWidget(artist_detail_widget)
            # TODO: Maybe fetch and add top tracks/albums below this widget too

        self.api_worker = None

    def create_artist_detail_view(self, artist_info):
        """Creates a widget showing detailed artist info (image, name, bio, etc.)."""
        detail_frame = QFrame()
        detail_frame.setObjectName("artist_detail_view") # Optional styling
        main_layout = QVBoxLayout(detail_frame)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top section: Image and Name/Stats
        top_layout = QHBoxLayout()
        top_layout.setSpacing(15)

        image_label = QLabel()
        img_size = 160 # Larger image for detail view
        image_label.setFixedSize(img_size, img_size)
        image_label.setStyleSheet("border: 1px solid #555; border-radius: 5px; background-color: #333;") # BG color for placeholder
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.request_image(artist_info.get('image_url'), image_label)
        top_layout.addWidget(image_label)

        name_stats_layout = QVBoxLayout()
        name_label = QLabel(f"<b>{artist_info.get('name', 'N/A')}</b>")
        name_label.setStyleSheet("font-size: 16pt; border: none; background: transparent;")
        name_stats_layout.addWidget(name_label)

        listeners = artist_info.get('listeners')
        playcount = artist_info.get('playcount')
        stats_text = f"{int(listeners):,} listeners | {int(playcount):,} plays" if listeners and playcount else "Stats N/A"
        stats_label = QLabel(stats_text)
        stats_label.setStyleSheet("color: #AAAAAA; border: none; background: transparent;")
        name_stats_layout.addWidget(stats_label)

        # Add Tags
        tags = artist_info.get('tags', [])
        if tags:
            tags_label = QLabel(f"Tags: {', '.join(tags[:6])}{'...' if len(tags) > 6 else ''}")
            tags_label.setWordWrap(True)
            tags_label.setToolTip(", ".join(tags)) # Show all tags on hover
            tags_label.setStyleSheet("color: #AAAAAA; font-size: 9pt; border: none; background: transparent;")
            name_stats_layout.addWidget(tags_label)

        name_stats_layout.addStretch()
        top_layout.addLayout(name_stats_layout)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)

        # Bio Section
        bio_summary = artist_info.get('bio_summary', 'No summary available.')
        # Clean up common Last.fm link format if present
        bio_summary = bio_summary.split('<a href=')[0].strip()

        if bio_summary:
            bio_group = QGroupBox("Bio Summary")
            # bio_group.setFlat(True) # Alternative style
            bio_layout = QVBoxLayout(bio_group)
            bio_label = QLabel(bio_summary)
            bio_label.setWordWrap(True)
            bio_label.setStyleSheet("color: #D0D0D0; background: transparent;") # Ensure label readable
            bio_layout.addWidget(bio_label)
            # Add a Read More button? (Future enhancement: use bio_content)
            main_layout.addWidget(bio_group)

        # Placeholder for Top Tracks / Albums Section (Future Enhancement)
        # ... add logic to fetch and display top tracks/albums here ...

        main_layout.addStretch()
        return detail_frame

    def search_error(self, error_message):
        self.status_label.setText("Status: Search Failed!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.search_scrobble_button.setEnabled(False)
        # Clear results on error too
        self._clear_search_results_layout()
        error_label = QLabel(f"Error: {error_message}")
        error_label.setStyleSheet("color: red;")
        self.search_results_layout.addWidget(error_label)

        self.api_worker = None
        QMessageBox.critical(self, "Search Error", error_message)

    def populate_scrobble_from_search(self, track_data):
        # This method is now called with track_data directly from double-click
        if not track_data:
            print("Warning: populate_scrobble_from_search called with empty track_data")
            return

        # Clear preview image on scrobble tab initially
        self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Fetching..."))

        artist = track_data.get('artist', '')
        track_name = track_data.get('name', '')

        if not artist or not track_name:
            QMessageBox.warning(self, "Data Error", "Selected track data is missing artist or track name.")
            self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Error"))
            return

        # Set status while fetching details
        self.status_label.setText(f"Status: Fetching detailed information for '{track_name}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        # Disable controls slightly differently - allow switching tabs maybe?
        # self.set_controls_enabled(False)

        # Create a worker to fetch detailed track info (needed for album cover URL)
        # Use track_data as fallback info
        self.api_worker = ApiWorker(get_track_info, artist, track_name)
        # Pass track_data to the finished handler for fallback
        self.api_worker.finished.connect(lambda result: self._populate_with_detailed_info(result if result else track_data))
        self.api_worker.error.connect(lambda error_msg: self._populate_with_basic_info(track_data, error_msg))
        self.api_worker.start()

    def _populate_with_detailed_info(self, track_info):
        """Populates the manual scrobble tab using detailed info (incl. cover). Falls back if needed."""
        self.set_controls_enabled(True)

        # Preferentially use data from track_info if it's the detailed dict
        # Fallback to using track_info as the basic dict if detailed fetch failed but passed basic data
        is_detailed = isinstance(track_info, dict) and 'album_title' in track_info # Heuristic

        artist = track_info.get('artist', '')
        track_name = track_info.get('name', '')
        album_title = track_info.get('album_title') if is_detailed else None
        image_url = track_info.get('image_url') # This should exist in both detailed and basic search results now

        # Populate the scrobble form fields
        self.artist_input.setText(artist)
        self.track_input.setText(track_name)
        if album_title:
            self.album_input.setText(album_title)
        elif not is_detailed: # If using basic data, clear album field
             self.album_input.clear()
        # else: keep potentially manually entered album if detailed fetch failed?
        #     pass # Keep existing text

        # Update image preview using the image_url found
        if image_url:
            self.request_image(image_url, self.manual_album_cover_label)
        else:
            self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "No Cover"))

        status_msg = f"Status: Track details loaded for '{track_name}'" + (" (detailed)" if is_detailed else " (basic)")
        self.status_label.setText(status_msg)
        self.status_label.setStyleSheet("color: green; font-weight: bold;")

        # Switch to scrobble tab and reset count
        self.tabs.setCurrentWidget(self.scrobble_tab)
        self.count_input.setValue(1)
        self.api_worker = None

    def _populate_with_basic_info(self, track_data, error_message=None):
        """Fall back to using the basic search result data if detailed info fetch fails."""
        self.set_controls_enabled(True)

        if error_message:
            print(f"Failed to get detailed track info: {error_message}")
            QMessageBox.warning(self, "Fetch Warning", f"Could not fetch full track details: {error_message}. Using basic info.")

        # Use the passed track_data (should be the basic result dict)
        if track_data:
            self.artist_input.setText(track_data.get('artist', ''))
            self.track_input.setText(track_data.get('name', ''))
            self.album_input.clear() # Clear album, as basic search often lacks it
            # Use image URL from basic data if available
            image_url = track_data.get('image_url')
            if image_url:
                self.request_image(image_url, self.manual_album_cover_label)
            else:
                self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "No Cover"))

            self.status_label.setText("Status: Basic track details loaded")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            # Should not happen if called correctly
            print("Error: _populate_with_basic_info called with no track_data")
            self.status_label.setText("Status: Error loading track details")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Error"))

        # Switch to scrobble tab and reset count
        self.tabs.setCurrentWidget(self.scrobble_tab)
        self.count_input.setValue(1)
        self.api_worker = None

    def scrobble_selected_search_result(self):
        # Use the selected item widget
        if not self.selected_search_item_widget:
             QMessageBox.warning(self, "No Selection", "Please select a track from the search results first by clicking on it.")
             return

        # Ensure the selected item is actually a track
        if self.selected_search_item_widget.property("item_type") != "track":
             QMessageBox.warning(self, "Invalid Selection", "Please select a track item to scrobble.")
             return

        track_data = self.selected_search_item_widget.property("track_data")
        if not track_data:
            QMessageBox.warning(self, "Error", "Could not retrieve data for the selected track.")
            return

        artist = track_data.get('artist', '')
        track_name = track_data.get('name', '')
        count = self.search_count_input.value()

        if not artist or not track_name:
            QMessageBox.warning(self, "Error", "Selected track data is incomplete.")
            return

        if count <= 0:
            QMessageBox.warning(self, "Invalid Count", "Scrobble count must be at least 1.")
            return

        # --- Display Confirmation --- #
        self._clear_search_results_layout()
        confirm_widget = self.create_confirmation_widget(track_data, count)
        self.search_results_layout.addWidget(confirm_widget)
        # -------------------------- #

        # Set status while fetching details
        self.status_label.setText(f"Status: Fetching detailed information for '{track_name}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls

        # Fetch detailed track info to get accurate album information
        # This worker reference will be overwritten by start_scrobble_task later
        self.api_worker = ApiWorker(get_track_info, artist, track_name)
        self.api_worker.finished.connect(lambda result: self._process_scrobble_with_details(result, count))
        self.api_worker.error.connect(lambda error: self._scrobble_with_basic_info(track_data, count))
        self.api_worker.start()

    def create_confirmation_widget(self, track_data, count):
        """Creates a widget confirming the track to be scrobbled."""
        item_frame = QFrame()
        item_frame.setObjectName("confirmation_item") # Different ID for potential styling
        item_frame.setFrameShape(QFrame.Shape.StyledPanel)
        item_frame.setLineWidth(1)
        # item_frame.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)) # Not clickable
        item_frame.setProperty("item_type", "confirmation") # Identify item type

        item_layout = QHBoxLayout(item_frame)
        item_layout.setContentsMargins(8, 8, 8, 8)
        item_layout.setSpacing(12)

        # Image Label
        image_label = QLabel()
        image_size = PLACEHOLDER_SIZE
        image_label.setFixedSize(image_size, image_size)
        image_label.setStyleSheet("border: none; border-radius: 4px;")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.request_image(track_data.get('image_url'), image_label)
        item_layout.addWidget(image_label)

        # Text Labels Layout
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        track_name = track_data.get('name', 'N/A')
        artist_name = track_data.get('artist', 'N/A')

        prep_label = QLabel("Preparing to scrobble:")
        prep_label.setStyleSheet("color: #AAAAAA; font-size: 9pt;")
        track_label = QLabel(f"<b>{track_name}</b>")
        artist_label = QLabel(artist_name)
        artist_label.setObjectName("artist_label")
        count_label = QLabel(f"({count} time{'' if count == 1 else 's'})" )
        count_label.setStyleSheet("color: #AAAAAA; font-size: 9pt;")

        text_layout.addWidget(prep_label)
        text_layout.addWidget(track_label)
        text_layout.addWidget(artist_label)
        text_layout.addWidget(count_label)
        text_layout.addStretch()

        item_layout.addLayout(text_layout)
        item_layout.addStretch()
        return item_frame

    def _process_scrobble_with_details(self, track_info, count):
        """Process scrobbling with detailed track information"""
        if track_info:
            # Extract track details (Corrected Artist Extraction)
            artist = track_info.get('artist', '') # Get artist name directly from the detailed info dict
            track_name = track_info.get('name', '')
            album_title = track_info.get('album_title') # Already extracted in get_track_info

            if not artist or not track_name:
                 # This case should be less likely if get_track_info succeeded
                 print("Error: Detailed track info missing artist or track name.")
                 # Fall back to basic info from the selected widget
                 if self.selected_search_item_widget:
                     track_data = self.selected_search_item_widget.property("track_data")
                     self._scrobble_with_basic_info(track_data, count)
                 else:
                      self.set_controls_enabled(True)
                      self.status_label.setText("Status: Scrobble failed - track details incomplete")
                      self.status_label.setStyleSheet("color: red; font-weight: bold;")
                      QMessageBox.warning(self, "Error", "Could not scrobble the track - details incomplete.")
                 # Don't clear api_worker here, let the caller handle it or final step clear it
                 return

            tracks_to_scrobble = [{
                'artist': artist,
                'track': track_name,
                'album': album_title,
                'count': count
            }]
            self.start_scrobble_task(tracks_to_scrobble=tracks_to_scrobble)
        else:
            # Fall back to basic info if detailed info could not be retrieved
            # Use data from the selected widget property
            track_data = None
            if self.selected_search_item_widget:
                track_data = self.selected_search_item_widget.property("track_data")

            if track_data:
                 self._scrobble_with_basic_info(track_data, count)
            else:
                 self.set_controls_enabled(True)
                 self.status_label.setText("Status: Scrobble failed - track details not available")
                 self.status_label.setStyleSheet("color: red; font-weight: bold;")
                 QMessageBox.warning(self, "Error", "Could not scrobble the track - details not available.")

        # REMOVED: self.api_worker = None # Let start_scrobble_task manage the worker reference

    def _scrobble_with_basic_info(self, track_data, count):
        """Fallback to scrobble using basic track information when detailed fetch fails."""
        if not track_data:
            self.set_controls_enabled(True)
            self.status_label.setText("Status: Scrobble failed - track data unavailable")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.warning(self, "Error", "Could not scrobble the track - track data unavailable.")
            return

        artist = track_data.get('artist', '')
        track_name = track_data.get('name', '')
        
        if not artist or not track_name:
            self.set_controls_enabled(True)
            self.status_label.setText("Status: Scrobble failed - track details incomplete")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.warning(self, "Error", "Could not scrobble the track - details incomplete.")
            return
            
        # Use the basic info without album (explicitly set to empty string rather than None)
        tracks_to_scrobble = [{
            'artist': artist,
            'track': track_name,
            'album': "",  # Empty string instead of None for better compatibility
            'count': count
        }]
        
        self.start_scrobble_task(tracks_to_scrobble=tracks_to_scrobble)

    # --- Album Fetch Logic ---
    def start_fetch_album_info_task(self):
        print("DEBUG: start_fetch_album_info_task called") # <<< Added Debug Print
        artist = self.album_artist_input.text().strip()
        album = self.album_name_input.text().strip()

        if not artist or not album:
            QMessageBox.warning(self, "Input Missing", "Please enter both Artist and Album name.")
            return

        self.status_label.setText(f"Status: Fetching info for album '{album}'...")
        self.status_label.setStyleSheet("color: #6495ED; background-color: #333; padding: 4px; border-radius: 3px;") # Bluish
        self.set_controls_enabled(False)
        self._clear_album_tracks_layout()
        self.album_cover_label.setPixmap(self.get_placeholder_pixmap(self.album_cover_label.sizeHint(), "Loading..."))
        self.album_info_label.setText("Fetching...")
        self.scrobble_album_button.setEnabled(False)
        self.current_album_artist = artist
        self.current_album_name = album
        self.api_worker = ApiWorker(get_album_info, artist, album)
        self.api_worker.finished.connect(self.album_info_finished)
        self.api_worker.error.connect(self.album_info_error)
        self.api_worker.start()

    def album_info_finished(self, album_info): # Renamed handler, receives full dict
        print(f"DEBUG: album_info_finished received type: {type(album_info)}, value: {album_info}") # <<< Added Debug Print
        self.set_controls_enabled(True) # Re-enable controls

        if album_info is None:
            # This means API call succeeded but album wasn't found or other issue
            self.status_label.setText(f"Status: Album '{self.current_album_name}' by '{self.current_album_artist}' not found.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self._clear_album_tracks_layout()
            self.album_tracks_layout.addWidget(QLabel("Album not found."))
            self.album_cover_label.setText("Album not found") # Use setText for placeholder text
            self.album_info_label.setText("")
            self.scrobble_album_button.setEnabled(False)
            QMessageBox.warning(self, "Fetch Failed", f"Could not find album '{self.current_album_name}' by '{self.current_album_artist}'. Check spelling or Last.fm listing.")
        # Add explicit check if it's a dictionary before using .get()
        elif isinstance(album_info, dict):
            # Album info found, extract tracks and display info
            track_list = album_info.get('tracks', []) # Get track list (list of dicts)
            fetched_artist = album_info.get('artist', self.current_album_artist)
            fetched_album = album_info.get('name', self.current_album_name)
            image_url = album_info.get('image_url')

            # Update album info display
            self.request_image(image_url, self.album_cover_label)
            self.album_info_label.setText(f"<b>{fetched_album}</b>\nby {fetched_artist}")
            # Store potentially corrected names
            self.current_album_artist = fetched_artist
            self.current_album_name = fetched_album

            self._clear_album_tracks_layout()
            if not track_list:
                 self.status_label.setText(f"Status: Found album '{fetched_album}' but it has no tracks listed.")
                 self.status_label.setStyleSheet("color: orange; font-weight: bold;")
                 self.album_tracks_layout.addWidget(QLabel("No tracks listed for this album."))
                 self.scrobble_album_button.setEnabled(False)
            else:
                self.status_label.setText(f"Status: Fetched {len(track_list)} tracks for '{fetched_album}'.")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                for i, track_dict in enumerate(track_list):
                     track_name = track_dict.get('name', 'Unknown Track')
                     track_label = QLabel(f"{i+1}. {track_name}")
                     track_label.setProperty("track_name", track_name) # Store name for scrobbling
                     self.album_tracks_layout.addWidget(track_label)
                # Enable scrobble button only if authenticated and tracks were found
                self.scrobble_album_button.setEnabled(bool(self.session_key))
        else:
            # Handle unexpected type (like the string that caused the error)
            print(f"ERROR: album_info_finished received unexpected type: {type(album_info)}")
            self.status_label.setText("Status: Error processing album info.")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self._clear_album_tracks_layout()
            self.album_tracks_layout.addWidget(QLabel("Error processing result."))
            self.album_cover_label.setText("Error")
            self.album_info_label.setText("Error")
            self.scrobble_album_button.setEnabled(False)
            QMessageBox.critical(self, "Processing Error", f"Received unexpected data type when fetching album info: {type(album_info)}")


        self.api_worker = None # Clear worker reference

    def album_info_error(self, error_message): # Renamed handler
        self.status_label.setText("Status: Failed to fetch album info!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.scrobble_album_button.setEnabled(False)
        self._clear_album_tracks_layout()
        self.album_tracks_layout.addWidget(QLabel(f"Error: {error_message}"))
        self.album_cover_label.setText("Error fetching")
        self.album_info_label.setText("")
        self.api_worker = None
        QMessageBox.critical(self, "Fetch Error", error_message)

    def _clear_album_tracks_layout(self):
        """Removes all widgets from the album tracks layout."""
        while self.album_tracks_layout.count():
            child = self.album_tracks_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # --- Album Scrobble Logic ---
    def start_scrobble_album_task(self):
        if not self.session_key:
             QMessageBox.critical(self, "Error", "Not authenticated.")
             return

        # --- Refined Check for Valid Tracks --- #
        has_valid_tracks = False
        if self.album_tracks_layout.count() > 0:
            first_widget = self.album_tracks_layout.itemAt(0).widget()
            # Check if the first widget is a QLabel *and* has our custom track_name property
            if isinstance(first_widget, QLabel) and first_widget.property("track_name") is not None:
                has_valid_tracks = True

        if not has_valid_tracks:
            QMessageBox.warning(self, "No Tracks", "No valid tracks fetched to scrobble. Please fetch album info first.")
            return
        # --- End Refined Check --- #

        # Check if tracks layout is empty or contains only info messages (Old Check - Replaced)
        # if self.album_tracks_layout.count() == 0 or isinstance(self.album_tracks_layout.itemAt(0).widget(), QLabel):
        #     first_widget_text = self.album_tracks_layout.itemAt(0).widget().text() if self.album_tracks_layout.count() > 0 else ""
        #     if "not found" in first_widget_text or "No tracks listed" in first_widget_text or "Error:" in first_widget_text:
        #         QMessageBox.warning(self, "No Tracks", "No valid tracks fetched to scrobble. Please fetch album info first.")
        #         return

        artist = self.current_album_artist # Use stored artist/album (potentially corrected by API)
        album = self.current_album_name
        count_per_track = self.album_count_input.value()

        if not artist or not album:
             QMessageBox.critical(self, "Error", "Missing album artist or name. Please fetch album info again.")
             return

        if count_per_track <= 0:
             QMessageBox.warning(self, "Invalid Count", "Scrobble count per track must be at least 1.")
             return

        tracks_to_scrobble = []
        # Iterate through widgets in the layout
        for i in range(self.album_tracks_layout.count()):
            widget = self.album_tracks_layout.itemAt(i).widget()
            # Ensure it's one of our track labels (which have the track_name property)
            track_name = widget.property("track_name") # Get property directly
            if isinstance(widget, QLabel) and track_name is not None:
                # track_name = widget.property("track_name") # Already got it
                tracks_to_scrobble.append({
                    'artist': artist,
                    'track': track_name,
                    'album': album,
                    'count': count_per_track
                })

        if not tracks_to_scrobble:
             # This should be less likely now due to the check at the start
             QMessageBox.warning(self, "Error", "Could not prepare track list for scrobbling (no valid tracks found in list).")
             return

        # Use the existing generic scrobble task function
        self.start_scrobble_task(tracks_to_scrobble=tracks_to_scrobble)

    # --- Generic Scrobble Task Starter ---
    def start_scrobble_task(self, tracks_to_scrobble=None):
        if not self.session_key:
            QMessageBox.critical(self, "Error", "Not authenticated. Please authenticate first.")
            return

        # --- Logic for 'Now Playing' Update ---
        # We'll call this before the confirmation dialog for immediate feedback
        # but after basic track info is gathered.

        current_artist = ""
        current_track = ""
        current_album = ""
        # --------------------------------------

        if not tracks_to_scrobble: # If called from the manual scrobble tab
            artist = self.artist_input.text().strip()
            track = self.track_input.text().strip()
            album = self.album_input.text().strip() or None
            count = self.count_input.value()

            if not artist or not track:
                QMessageBox.warning(self, "Input Missing", "Please enter Artist and Track.")
                return
            if count <= 0:
                 QMessageBox.warning(self, "Invalid Count", "Scrobble count must be at least 1.")
                 return

            tracks_to_scrobble = [{
                'artist': artist,
                'track': track,
                'album': album,
                'count': count
            }]
            current_artist, current_track, current_album = artist, track, album

        else: # Called with a list (e.g., from search or album scrobble)
            if tracks_to_scrobble:
                first_track_info = tracks_to_scrobble[0]
                current_artist = first_track_info.get('artist', '')
                current_track = first_track_info.get('track', '')
                current_album = first_track_info.get('album')

        # --- Call 'Update Now Playing' if checkbox is checked and we have a track ---
        if self.now_playing_checkbox.isChecked() and current_artist and current_track:
            print(f"Updating Now Playing: {current_artist} - {current_track}")
            # We can display the image of the 'Now Playing' track in the manual scrobble preview
            # To do this robustly, we might need to fetch full track info if not already available
            # For simplicity now, let's assume basic info is enough for the call, then fetch image
            
            # Fetch detailed info for image and accurate data for Now Playing
            self.api_worker_now_playing = ApiWorker(get_track_info, current_artist, current_track)
            # Chain the actual now_playing call after getting track_info
            self.api_worker_now_playing.finished.connect(
                lambda track_info_result: self._handle_now_playing_update(track_info_result, current_album)
            )
            self.api_worker_now_playing.error.connect(
                lambda error_msg: self.status_label.setText(f"Status: Now Playing update failed: {error_msg}")
            )
            self.api_worker_now_playing.start()
            # Note: The scrobble confirmation will proceed without waiting for this to finish.
            # This is a design choice for responsiveness. User will see status updates.
            self.status_label.setText(f"Status: Sending 'Now Playing' for {current_track}...")
            self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        # ----------------------------------------------------------------------

        total_scrobbles = sum(t['count'] for t in tracks_to_scrobble)
        if total_scrobbles == 0:
             QMessageBox.warning(self, "No Scrobbles", "No tracks or zero count specified.")
             return

        # Confirmation Dialog
        confirm_msg = f"This will submit {total_scrobbles} scrobble(s) in total.\n\n"
        # Show details for the first few tracks only if it's a long list (e.g., album)
        max_preview = 5
        for i, t in enumerate(tracks_to_scrobble):
             if i < max_preview:
                 confirm_msg += f"- {t['track']} by {t['artist']} ({t['count']} times)\n"
             elif i == max_preview:
                 confirm_msg += f"- ...and {len(tracks_to_scrobble) - max_preview} more track(s)\n"
        confirm_msg += "\nProceed?"

        reply = QMessageBox.question(self, 'Confirm Scrobble', confirm_msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.No:
            self.status_label.setText("Status: Scrobble cancelled.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # If cancelled here, should clear confirmation widget in search tab too
            if self.tabs.currentWidget() == self.search_tab:
                self._clear_search_results_layout()
            return

        self.status_label.setText("Status: Scrobbliing...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during scrobble

        # Setup and show progress dialog
        self.progress_dialog = QProgressDialog("Scrobbling...", "Cancel", 0, total_scrobbles, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_task)
        self.progress_dialog.show()

        # Run scrobbling in worker thread
        self.api_worker = ApiWorker(scrobble_multiple_tracks,
                                    tracks_info=tracks_to_scrobble,
                                    session_key=self.session_key,
                                    base_timestamp=int(time.time()))
        self.api_worker.finished.connect(self.scrobble_finished)
        self.api_worker.error.connect(self.scrobble_error)
        self.api_worker.progress.connect(self.update_progress)
        self.api_worker.start()

    def scrobble_finished(self, result):
        # Clear confirmation widget from search tab if present
        if self.tabs.currentWidget() == self.search_tab:
             self._clear_search_results_layout()

        if self.progress_dialog:
            self.progress_dialog.close()

        if result is None: # Should not happen if not cancelled, but check
             self.status_label.setText(f"Status: Scrobble finished unexpectedly.")
             self.status_label.setStyleSheet("color: orange; font-weight: bold;")
             QMessageBox.warning(self, "Scrobble Info", "Scrobbling finished, but no results were returned (possibly cancelled early).")
        else:
            success_count, failure_count = result
            self.status_label.setText(f"Status: Scrobble complete. Success: {success_count}, Failed: {failure_count}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;" if failure_count == 0 else "color: orange; font-weight: bold;")
            QMessageBox.information(self, "Scrobble Complete", f"Successfully sent {success_count} scrobbles.\n{failure_count} scrobbles failed or were ignored.")

        self.set_controls_enabled(True)
        self.api_worker = None # Clear worker reference *after* task is finished

    def scrobble_error(self, error_message):
        # Clear confirmation widget from search tab if present
        if self.tabs.currentWidget() == self.search_tab:
             self._clear_search_results_layout()

        if self.progress_dialog:
            self.progress_dialog.close()
        self.status_label.setText("Status: Scrobble Failed!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.api_worker = None # Clear worker reference *after* task error
        QMessageBox.critical(self, "Scrobble Error", error_message)

    def update_progress(self, current_count, total_count, message):
        if self.progress_dialog:
            # Ensure total is set correctly
            if self.progress_dialog.maximum() != total_count:
                 self.progress_dialog.setMaximum(total_count)
            self.progress_dialog.setValue(current_count)
            # Make label more informative for albums vs single tracks
            base_label = "Scrobbling..."
            if self.tabs.currentWidget() == self.album_tab:
                 base_label = f"Scrobbling Album '{self.current_album_name}'..."
            elif self.tabs.currentWidget() == self.search_tab:
                 base_label = "Scrobbling Search Result..."
            else:
                 base_label = f"Scrobbling Track '{self.artist_input.text()}'..."

            self.progress_dialog.setLabelText(f"{base_label} ({message})")
            QApplication.processEvents() # Keep UI responsive

    # --- Cancellation Logic ---
    def cancel_task(self):
        """Requests interruption for the API worker and aborts pending image downloads."""
        interrupted = False
        if self.api_worker and self.api_worker.isRunning():
            print("Attempting to cancel API task...")
            self.api_worker.requestInterruption() # Request interruption
            interrupted = True
            # Don't terminate forcefully here, let the thread finish if it can check
            # The worker thread now checks self._is_interruption_requested

        # Abort pending image downloads
        if self.pending_replies:
             print(f"Aborting {len(self.pending_replies)} pending image downloads...")
             # Iterate over a copy of the set as abort() might trigger finished signal
             # which modifies the set via handle_image_reply
             replies_to_abort = list(self.pending_replies)
             for reply in replies_to_abort:
                 if reply and reply.isRunning():
                     print(f"  Aborting: {reply.url().toString()}")
                     reply.abort() # This will emit finished with OperationCanceledError
                     # handle_image_reply will remove it from self.pending_replies
             interrupted = True # Mark as interrupted even if only images were cancelled

        if interrupted:
            self.status_label.setText("Status: Task Cancellation Requested")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # Re-enable controls immediately upon requesting cancel
            self.set_controls_enabled(True)
            if self.progress_dialog and self.progress_dialog.isVisible():
                self.progress_dialog.setLabelText("Cancelling...")
                # The finished/error signal from the worker will close the dialog
            print("Task cancellation requested. Waiting for thread/network replies to acknowledge.")
        elif self.progress_dialog and self.progress_dialog.isVisible():
             # If progress dialog exists but no worker/replies (shouldn't happen often)
             self.progress_dialog.close()
        # else: No task was running

    # --- Utility Functions ---
    def set_controls_enabled(self, enabled, keep_search_inputs=False):
        is_authenticated = bool(self.session_key)

        # --- Check Search Results State (Still needed for Scrobble Button) --- #
        search_results_are_tracks = False
        search_results_are_artists = False
        search_results_is_artist_detail = False
        if self.search_results_layout.count() > 0:
            first_widget = self.search_results_layout.itemAt(0).widget()
            if isinstance(first_widget, QFrame):
                item_type = first_widget.property("item_type")
                if item_type == "track":
                    search_results_are_tracks = True
                elif item_type == "artist":
                    search_results_are_artists = True
                elif first_widget.objectName() == "artist_detail_view":
                    search_results_is_artist_detail = True

        # --- Check Album Tracks State (Still needed for Scrobble Button) --- #
        has_real_album_tracks = False
        if self.album_tracks_layout.count() > 0:
            first_album_widget = self.album_tracks_layout.itemAt(0).widget()
            if isinstance(first_album_widget, QLabel) and first_album_widget.property("track_name") is not None:
                has_real_album_tracks = True

        # --- Enable/Disable Controls --- #
        # print(f"DEBUG: set_controls_enabled(enabled={enabled}, is_auth={is_authenticated}, search_tracks={search_results_are_tracks}, album_tracks={has_real_album_tracks})")

        # General Auth Button
        self.auth_button.setEnabled(enabled and not is_authenticated)
        self.auth_button.setText("Authenticated" if is_authenticated else "Authenticate")

        # Scrobble Tab
        self.artist_input.setEnabled(enabled)
        self.track_input.setEnabled(enabled)
        self.album_input.setEnabled(enabled)
        self.fetch_manual_album_info_button.setEnabled(enabled and is_authenticated)
        self.count_input.setEnabled(enabled)
        self.scrobble_button.setEnabled(enabled and is_authenticated)

        # Search Tab
        self.search_artist_input.setEnabled(enabled or keep_search_inputs)
        self.search_track_input.setEnabled(enabled or keep_search_inputs)
        self.search_results_scroll_area.setEnabled(enabled)

        # SIMPLIFIED: Enable search count input whenever authenticated and not busy
        search_count_should_be_enabled = enabled and is_authenticated
        # print(f"DEBUG: Setting search_count_input enabled: {search_count_should_be_enabled}")
        self.search_count_input.setEnabled(search_count_should_be_enabled)

        # Enable search scrobble button ONLY if a track is selected
        can_scrobble_selected = isinstance(self.selected_search_item_widget, QFrame) and self.selected_search_item_widget.property("item_type") == "track"
        search_scrobble_should_be_enabled = enabled and is_authenticated and can_scrobble_selected
        # print(f"DEBUG: Setting search_scrobble_button enabled: {search_scrobble_should_be_enabled}")
        self.search_scrobble_button.setEnabled(search_scrobble_should_be_enabled)

        # Album Tab
        self.album_artist_input.setEnabled(enabled)
        self.album_name_input.setEnabled(enabled)
        self.fetch_tracks_button.setEnabled(enabled and is_authenticated)
        self.album_tracks_scroll_area.setEnabled(enabled)

        # SIMPLIFIED: Enable album count input whenever authenticated and not busy
        album_count_should_be_enabled = enabled and is_authenticated
        # print(f"DEBUG: Setting album_count_input enabled: {album_count_should_be_enabled}")
        self.album_count_input.setEnabled(album_count_should_be_enabled)

        # Enable album scrobble button ONLY if real tracks are loaded
        album_scrobble_should_be_enabled = enabled and is_authenticated and has_real_album_tracks
        # print(f"DEBUG: Setting scrobble_album_button enabled: {album_scrobble_should_be_enabled}")
        self.scrobble_album_button.setEnabled(album_scrobble_should_be_enabled)

    # --- Dynamic Search Logic ---
    def trigger_dynamic_search(self):
        """Triggered when the search timer times out, performs the actual search."""
        artist = self.search_artist_input.text().strip()
        track = self.search_track_input.text().strip()

        # We need at least an artist name to search
        if not artist:
            self._clear_search_results_layout()
            no_input_label = QLabel("Please enter an artist name to start searching.")
            no_input_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.search_results_layout.addWidget(no_input_label)
            self.selected_search_item_widget = None # Reset selection
            self.search_scrobble_button.setEnabled(False)
            return

        self.status_label.setText(f"Status: Searching...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")

        # Disable scrobble button during search
        self.search_scrobble_button.setEnabled(False)
        self.set_controls_enabled(False, keep_search_inputs=True) # Keep search inputs enabled

        # Determine if searching for artists or tracks based on input
        if track: # If track is specified, always search tracks
            print(f"Searching TRACK: {track} by {artist}")
            self.api_worker = ApiWorker(search_track, artist, track)
            self.api_worker.finished.connect(self.search_tracks_finished)
        else: # If only artist is specified, search artists
            print(f"Searching ARTIST: {artist}")
            self.api_worker = ApiWorker(search_artist, artist)
            self.api_worker.finished.connect(self.search_artists_finished)

        self.api_worker.error.connect(self.search_error)
        self.api_worker.start()

    def on_search_text_changed(self):
        """Called when either search field text changes. Starts/restarts the search timer."""
        # Cancel any existing worker doing a previous search
        if self.api_worker and self.api_worker.isRunning():
            print("Search text changed, cancelling previous API worker...")
            self.cancel_task() # Request interruption of the API call

        # Cancel any existing search timer
        self.search_timer.stop()

        # Start timer with a delay of 500ms
        self.search_timer.start(500)

        # Update status to show we're preparing to search
        self.status_label.setText("Status: Typing...")
        self.status_label.setStyleSheet("color: gray; font-weight: normal;")

    def closeEvent(self, event):
        # Ensure worker thread and network requests are stopped if app closes
        if (self.api_worker and self.api_worker.isRunning()) or self.pending_replies:
            print("Window closing, requesting task/download interruption...")
            self.cancel_task() # Try to clean up API worker and image downloads
            # Give it a moment to potentially stop
            if self.api_worker:
                 self.api_worker.wait(300) # Wait short time
            # Check again for worker
            if self.api_worker and self.api_worker.isRunning():
                 print("Worker still running after wait, terminating forcefully.")
                 self.api_worker.terminate() # Force stop if still running
                 self.api_worker.wait() # Wait for termination
        event.accept()

    # --- Manual Scrobble Tab Logic ---
    def fetch_album_info_for_manual_scrobble(self):
        artist = self.artist_input.text().strip()
        album = self.album_input.text().strip()

        if not artist or not album:
            QMessageBox.warning(self, "Input Missing", "Please enter both Artist and Album name to fetch info.")
            return

        self.status_label.setText(f"Status: Fetching info for album '{album}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during fetch
        self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Fetching..."))

        # Run fetch in worker thread
        self.api_worker = ApiWorker(get_album_info, artist, album)
        self.api_worker.finished.connect(self.manual_album_info_finished)
        self.api_worker.error.connect(self.manual_album_info_error)
        self.api_worker.start()

    def manual_album_info_finished(self, album_info):
        self.set_controls_enabled(True) # Re-enable controls

        if album_info and album_info.get('image_url'):
            image_url = album_info.get('image_url')
            fetched_artist = album_info.get('artist')
            fetched_album = album_info.get('name')

            self.request_image(image_url, self.manual_album_cover_label)
            self.status_label.setText(f"Status: Album info loaded for '{fetched_album}'.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            # Optionally update artist/album fields if they were different or empty
            # self.artist_input.setText(fetched_artist)
            # self.album_input.setText(fetched_album)
        elif album_info: # Found info but no image
             fetched_album = album_info.get('name', self.album_input.text().strip())
             self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "No Cover"))
             self.status_label.setText(f"Status: Album info found for '{fetched_album}', but no cover image.")
             self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            # Album not found or error occurred (error signal should handle API errors)
            self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Not Found"))
            self.status_label.setText(f"Status: Could not find album info.")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.warning(self, "Fetch Failed", f"Could not find album info for '{self.album_input.text().strip()}' by '{self.artist_input.text().strip()}'.")

        self.api_worker = None

    def manual_album_info_error(self, error_message):
        self.set_controls_enabled(True)
        self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "Error"))
        self.status_label.setText("Status: Failed to fetch album info!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.api_worker = None
        QMessageBox.critical(self, "Fetch Error", error_message)

    # --- Search Logic --- #
    def _clear_search_results_layout(self):
        """Removes all widgets from the search results layout."""
        # Also reset selection state
        self.selected_search_item_widget = None
        self.search_scrobble_button.setEnabled(False)
        # Clear layout items
        while self.search_results_layout.count():
            child = self.search_results_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # --- Handler for after get_track_info for Now Playing ---
    def _handle_now_playing_update(self, track_info, original_album_context):
        if not self.session_key:
            return # Not authenticated

        artist_to_update = ""
        track_to_update = ""
        album_to_update = ""
        image_url_to_display = None

        if track_info: # Detailed info fetched successfully
            artist_to_update = track_info.get('artist', '')
            track_to_update = track_info.get('name', '')
            album_to_update = track_info.get('album_title') # Use specific album_title from get_track_info
            image_url_to_display = track_info.get('image_url')
            # Update the manual scrobble tab's preview image
            if image_url_to_display:
                self.request_image(image_url_to_display, self.manual_album_cover_label)
            else:
                self.manual_album_cover_label.setPixmap(self.get_placeholder_pixmap(self.manual_album_cover_label.sizeHint(), "No Cover"))
        else: # Fallback if get_track_info failed, use originally passed context
            # This situation should be less common if the track exists
            # We'd need to grab artist/track from somewhere if this path is taken without prior context
            # For now, this assumes `start_scrobble_task` set up `current_artist` and `current_track`
            # The following is a bit redundant if track_info is None, let's rely on prior context if available
            # Let's assume `current_artist`, `current_track`, `current_album` were set in `start_scrobble_task`
            # This path needs refinement if `track_info` is None and no prior context exists.
            # For safety, we should check if we have artist/track to update.
            # This code is called from a lambda that has `current_album` (original_album_context)
            # We need artist/track. Let's assume they were valid to initiate the get_track_info call.
            # This part of the logic is tricky because api_worker_now_playing might be for a different track
            # than what is currently in artist_input etc. Let's pass them through the lambda or store them.
            # For now, this is simplified and might not always pick the right track if UI changes rapidly.
            # A better approach: pass artist/track to this handler. Let's refine the lambda connection.
            # For now, if track_info is None, we don't have enough to reliably update Now Playing or image.
            self.status_label.setText(f"Status: Could not get track details for Now Playing.")
            return

        if not artist_to_update or not track_to_update:
            self.status_label.setText(f"Status: Missing artist/track for Now Playing update.")
            return

        # Worker for the actual updateNowPlaying API call
        self.api_worker_update = ApiWorker(
            update_now_playing,
            session_key=self.session_key,
            artist=artist_to_update,
            track=track_to_update,
            album=album_to_update  # Use potentially more accurate album from track_info
        )
        self.api_worker_update.finished.connect(self._now_playing_api_finished)
        self.api_worker_update.error.connect(self._now_playing_api_error)
        self.api_worker_update.start()

    def _now_playing_api_finished(self, success):
        if success:
            self.status_label.setText(f"Status: 'Now Playing' updated successfully.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(f"Status: Failed to update 'Now Playing' (API).")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        # Potentially clear this worker ref: self.api_worker_update = None

    def _now_playing_api_error(self, error_message):
        self.status_label.setText(f"Status: Error updating 'Now Playing': {error_message}")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        # Potentially clear this worker ref: self.api_worker_update = None
    # -----------------------------------------------------


# --- Application Entry Point ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set the stylesheet - Kawaii but Fierce Theme
    app.setStyleSheet("""
    /* Global Settings */
    QWidget {
        font-family: "Helvetica Neue", Arial, sans-serif;
        font-size: 10pt;
        color: #212121; /* Rich dark text */
        background-color: #fff0f5; /* Light pink background */
    }

    /* Group Boxes */
    QGroupBox {
        background-color: #ffe6ee; /* Soft pink */
        border: 2px solid #ff85a2; /* Hot pink border */
        border-radius: 8px;
        margin-top: 20px;
        padding-top: 10px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 5px 15px;
        margin-left: 10px;
        border-radius: 6px;
        background-color: #ff85a2; /* Hot pink */
        color: #ffffff;
        font-weight: bold;
        letter-spacing: 1px;
    }

    /* Labels */
    QLabel {
        background-color: transparent;
        color: #212121; /* Rich dark text */
        padding: 2px;
    }
    QLabel#status_label {
        font-weight: bold;
        padding: 6px;
        border-radius: 8px;
        border: 1px solid #ff85a2;
        letter-spacing: 0.5px;
    }

    /* LineEdits and SpinBoxes */
    QLineEdit, QSpinBox {
        background-color: #ffffff;
        border: 2px solid #ff85a2; /* Hot pink border */
        border-radius: 6px;
        padding: 6px 8px;
        color: #212121;
        selection-background-color: #ff85a2;
        selection-color: #ffffff;
    }
    QLineEdit:focus, QSpinBox:focus {
        border: 2px solid #ff4d94; /* Deeper pink for focus */
        background-color: #fffafa; /* Snow white */
    }
    QLineEdit::placeholderText {
        color: #b5a3b0; /* Muted mauve */
    }

    /* Buttons */
    QPushButton {
        background-color: #cc0066; /* Much deeper pink for maximum visibility */
        color: #ffffff;
        border: 2px solid #ff85a2; /* Add border for better contrast */
        border-radius: 8px;
        padding: 8px 16px;
        min-width: 100px;
        font-weight: bold;
        letter-spacing: 1px;
    }
    QPushButton:hover {
        background-color: #ff4d94; /* Lighter on hover for feedback */
        border: 2px solid #ff4d94;
    }
    QPushButton:pressed {
        background-color: #cc0066; /* Rich magenta when pressed */
        border: none;
        padding-top: 9px;
        padding-bottom: 7px;
    }
    QPushButton:disabled {
        background-color: #e0c0ce; /* Desaturated pink */
        color: #ffffff;
        border: none;
    }

    /* Checkboxes */
    QCheckBox {
        spacing: 8px;
        color: #212121;
    }
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border: 2px solid #ff85a2;
        border-radius: 4px;
    }
    QCheckBox::indicator:checked {
        background-color: #ff4d94;
        border: 2px solid #ff4d94;
        image: url(data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 18 18"><path fill="%23ffffff" d="M6.5 13.5L2 9l1.5-1.5L6.5 10.5 14 3l1.5 1.5z"/></svg>);
    }
    QCheckBox::indicator:unchecked {
        background-color: #ffffff;
    }

    /* Tabs */
    QTabWidget::pane {
        border: 2px solid #ff85a2;
        border-top: none;
        background-color: #fff5f8; /* Very light pink */
        border-bottom-left-radius: 8px;
        border-bottom-right-radius: 8px;
    }
    QTabWidget::tab-bar {
        left: 5px;
        alignment: left;
    }
    QTabBar::tab {
        background: #ffd3e0; /* Light pink */
        border: 2px solid #ff85a2;
        border-bottom: none;
        padding: 8px 16px;
        margin-right: 3px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        color: #212121;
        font-weight: bold;
    }
    QTabBar::tab:selected {
        background: #fff5f8; /* Match pane background */
        margin-bottom: -2px;
        color: #ff4d94; /* Deep pink text when selected */
        border: 2px solid #ff85a2;
        border-bottom: 2px solid #fff5f8;
    }
    QTabBar::tab:!selected:hover {
        background: #ffc1d6; /* Medium pink on hover */
        color: #212121;
    }

    /* Scroll Area and Contents */
    QScrollArea {
        border: none;
        background-color: transparent;
    }
    #search_results_widget, #album_tracks_widget {
        background-color: #fff5f8; /* Very light pink */
    }

    /* Search Result Item Frame */
    QFrame#search_result_item {
        background-color: #ffffff;
        border: 2px solid #ffd3e0;
        border-radius: 8px;
        padding: 8px;
    }
    QFrame#search_result_item:hover {
        background-color: #fff0f5;
        border: 2px solid #ff85a2;
    }
    QFrame#search_result_item[selected="true"] {
        background-color: #ffd3e0;
        border: 2px solid #ff4d94;
    }
    QFrame#search_result_item QLabel {
        background-color: transparent;
        border: none;
    }
    QFrame#search_result_item[selected="true"] QLabel {
        color: #212121;
    }
    QFrame#search_result_item[selected="true"] QLabel#artist_label {
        color: #7f5c7f; /* Slightly lighter purple in selected item */
    }

    /* Album Track Labels */
    #album_tracks_widget QLabel {
        padding: 6px 8px;
        border-bottom: 1px solid #ffd3e0;
        border-radius: 6px;
    }
    #album_tracks_widget QLabel:hover {
        background-color: #ffd3e0;
    }

    /* Scroll Bars */
    QScrollBar:vertical {
        border: none;
        background: #fff0f5;
        width: 12px;
        margin: 0px 0px 0px 0px;
    }
    QScrollBar::handle:vertical {
        background: #ff85a2;
        min-height: 25px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical:hover {
        background: #ff4d94;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
        background: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
    QScrollBar:horizontal {
        border: none;
        background: #fff0f5;
        height: 12px;
        margin: 0px 0px 0px 0px;
    }
    QScrollBar::handle:horizontal {
        background: #ff85a2;
        min-width: 25px;
        border-radius: 6px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #ff4d94;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
        background: none;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: none;
    }

    /* Progress Dialog */
    QProgressDialog {
        background-color: #fff5f8;
        border: 2px solid #ff85a2;
        border-radius: 8px;
    }
    QProgressDialog QLabel {
        color: #212121;
        padding: 5px;
    }
    QProgressBar {
        border: 2px solid #ff85a2;
        border-radius: 6px;
        text-align: center;
        background-color: #fff0f5;
        color: #212121;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff85a2, stop:1 #ff4d94);
        border-radius: 5px;
        margin: 2px;
    }
    QProgressDialog QPushButton {
        min-width: 80px;
        padding: 6px 12px;
    }

    /* Message Boxes */
    QMessageBox {
        background-color: #fff5f8;
    }
    QMessageBox QLabel {
        color: #212121;
    }
    QMessageBox QPushButton {
        min-width: 80px;
        padding: 6px 12px;
    }
    """)
    
    ex = LastfmScrobblerApp()
    ex.show()
    sys.exit(app.exec())

