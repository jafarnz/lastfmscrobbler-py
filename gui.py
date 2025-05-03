\
import sys
import time
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QListWidget, QListWidgetItem, # Added QListWidgetItem
    QMessageBox, QProgressDialog, QGroupBox, QFormLayout, QRadioButton,
    QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Import API functions and exception from main.py
from main import (
    get_session_key, search_track, get_album_tracks, scrobble_multiple_tracks,
    LastfmApiError, API_KEY, API_SECRET, USERNAME, PASSWORD
)

# --- Worker Thread for API Calls ---
# To prevent the GUI from freezing during network requests
class ApiWorker(QThread):
    # Signals to communicate back to the main GUI thread
    finished = pyqtSignal(object) # Can carry results or error info
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str) # current_count, total_count, message

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


# --- Main Application Window ---
class LastfmScrobblerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.session_key = None
        self.api_worker = None # To hold the worker thread instance
        self.progress_dialog = None # To show progress during long tasks
        self.current_album_artist = None # Store artist for album scrobble
        self.current_album_name = None # Store album name for album scrobble
        self.init_ui()
        self.authenticate() # Try to authenticate on startup

    def init_ui(self):
        self.setWindowTitle('Last.fm Mass Scrobbler')
        self.setGeometry(100, 100, 650, 500) # Increased size slightly

        self.main_layout = QVBoxLayout(self)

        # Status Label (for auth status, errors, etc.)
        self.status_label = QLabel("Status: Not Authenticated")
        self.status_label.setStyleSheet("color: red; font-weight: bold;") # Make it bolder
        self.main_layout.addWidget(self.status_label)

        # --- Tabs for different functions ---
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # -- Scrobble Tab --
        self.scrobble_tab = QWidget()
        self.tabs.addTab(self.scrobble_tab, "Single/Manual Scrobble") # Renamed tab
        self.scrobble_layout = QVBoxLayout(self.scrobble_tab)

        # Input Group
        scrobble_input_group = QGroupBox("Scrobble Details")
        scrobble_form_layout = QFormLayout()

        self.artist_input = QLineEdit()
        self.track_input = QLineEdit()
        self.album_input = QLineEdit() # Optional album
        self.count_input = QSpinBox()
        self.count_input.setRange(1, 2800) # Sensible range
        self.count_input.setValue(1)
        self.count_input.setToolTip("How many times to scrobble this specific track.")

        scrobble_form_layout.addRow("Artist:", self.artist_input)
        scrobble_form_layout.addRow("Track:", self.track_input)
        scrobble_form_layout.addRow("Album (Optional):", self.album_input)
        scrobble_form_layout.addRow("Scrobble Count:", self.count_input)
        scrobble_input_group.setLayout(scrobble_form_layout)
        self.scrobble_layout.addWidget(scrobble_input_group)

        # Scrobble Button
        self.scrobble_button = QPushButton("Scrobble Track(s)")
        self.scrobble_button.setEnabled(False) # Disabled until authenticated
        self.scrobble_button.setStyleSheet("padding: 5px;") # Add padding
        self.scrobble_button.clicked.connect(self.start_scrobble_task)
        self.scrobble_layout.addWidget(self.scrobble_button)

        # Spacer to push elements up
        self.scrobble_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))


        # -- Search Tab --
        self.search_tab = QWidget()
        self.tabs.addTab(self.search_tab, "Search & Scrobble")
        self.search_layout = QVBoxLayout(self.search_tab)

        # Search Input Group
        search_input_group = QGroupBox("Search Last.fm Track")
        search_form_layout = QFormLayout()
        self.search_artist_input = QLineEdit()
        self.search_track_input = QLineEdit()
        self.search_button = QPushButton("Search Track")
        self.search_button.setStyleSheet("padding: 5px;")
        self.search_button.clicked.connect(self.start_search_task)

        search_form_layout.addRow("Artist:", self.search_artist_input)
        search_form_layout.addRow("Track:", self.search_track_input)
        search_input_group.setLayout(search_form_layout)
        self.search_layout.addWidget(search_input_group)
        self.search_layout.addWidget(self.search_button)


        # Search Results Group
        search_results_group = QGroupBox("Search Results (Double-click to populate Scrobble tab)")
        search_results_layout = QVBoxLayout()
        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.populate_scrobble_from_search) # Double-click to use
        search_results_layout.addWidget(self.search_results_list)

        # Scrobble from Search controls
        search_scrobble_layout = QHBoxLayout()
        search_scrobble_layout.addWidget(QLabel("Scrobble Count:"))
        self.search_count_input = QSpinBox()
        self.search_count_input.setRange(1, 50) # Lower default for search results
        self.search_count_input.setValue(1)
        search_scrobble_layout.addWidget(self.search_count_input)
        self.search_scrobble_button = QPushButton("Scrobble Selected Track")
        self.search_scrobble_button.setStyleSheet("padding: 5px;")
        self.search_scrobble_button.setEnabled(False) # Needs auth and selection
        self.search_scrobble_button.clicked.connect(self.scrobble_selected_search_result)
        search_scrobble_layout.addWidget(self.search_scrobble_button)

        search_results_layout.addLayout(search_scrobble_layout)
        search_results_group.setLayout(search_results_layout)
        self.search_layout.addWidget(search_results_group)


        # -- Album Scrobble Tab --
        self.album_tab = QWidget()
        self.tabs.addTab(self.album_tab, "Album Scrobble")
        self.album_layout = QVBoxLayout(self.album_tab)

        # Album Input Group
        album_input_group = QGroupBox("Album Details")
        album_form_layout = QFormLayout()
        self.album_artist_input = QLineEdit()
        self.album_name_input = QLineEdit()
        self.fetch_tracks_button = QPushButton("Fetch Album Tracks")
        self.fetch_tracks_button.setStyleSheet("padding: 5px;")
        self.fetch_tracks_button.setEnabled(False) # Needs auth
        self.fetch_tracks_button.clicked.connect(self.start_fetch_album_tracks_task)

        album_form_layout.addRow("Artist:", self.album_artist_input)
        album_form_layout.addRow("Album:", self.album_name_input)
        album_input_group.setLayout(album_form_layout)
        self.album_layout.addWidget(album_input_group)
        self.album_layout.addWidget(self.fetch_tracks_button)

        # Album Tracks Group
        album_tracks_group = QGroupBox("Fetched Tracks")
        album_tracks_layout = QVBoxLayout()
        self.album_tracks_list = QListWidget()
        self.album_tracks_list.setToolTip("List of tracks found for the specified album.")
        album_tracks_layout.addWidget(self.album_tracks_list)

        # Scrobble Album Controls
        album_scrobble_layout = QHBoxLayout()
        album_scrobble_layout.addWidget(QLabel("Scrobbles per Track:"))
        self.album_count_input = QSpinBox()
        self.album_count_input.setRange(1, 50) # Sensible limit per track for albums
        self.album_count_input.setValue(1)
        self.album_count_input.setToolTip("How many times EACH track in the list will be scrobbled.")
        album_scrobble_layout.addWidget(self.album_count_input)

        self.scrobble_album_button = QPushButton("Scrobble Entire Album")
        self.scrobble_album_button.setStyleSheet("padding: 5px;")
        self.scrobble_album_button.setEnabled(False) # Needs tracks fetched and auth
        self.scrobble_album_button.clicked.connect(self.start_scrobble_album_task)
        album_scrobble_layout.addWidget(self.scrobble_album_button)

        album_tracks_layout.addLayout(album_scrobble_layout)
        album_tracks_group.setLayout(album_tracks_layout)
        self.album_layout.addWidget(album_tracks_group)


        # --- Authentication Button (if needed) ---
        self.auth_button = QPushButton("Re-authenticate")
        self.auth_button.setStyleSheet("padding: 5px;")
        self.auth_button.clicked.connect(self.authenticate)
        self.main_layout.addWidget(self.auth_button)

    # --- Authentication Logic ---
    def authenticate(self):
        self.status_label.setText("Status: Authenticating...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during auth
        # Run auth in worker thread
        self.api_worker = ApiWorker(get_session_key) # Use imported function
        self.api_worker.finished.connect(self.auth_finished)
        self.api_worker.error.connect(self.auth_error)
        self.api_worker.start()

    def auth_finished(self, session_key):
        if session_key:
            self.session_key = session_key
            self.status_label.setText("Status: Authenticated Successfully")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.set_controls_enabled(True) # Enable controls now
            self.auth_button.setText("Authenticated") # Change button text
            self.auth_button.setEnabled(False) # Disable re-auth button for now
        else:
            # Should be caught by auth_error, but handle just in case
            self.status_label.setText("Status: Authentication Failed (Unknown Reason)")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.set_controls_enabled(True) # Re-enable controls
            self.auth_button.setText("Re-authenticate")
            self.auth_button.setEnabled(True)
            QMessageBox.critical(self, "Authentication Error", "Failed to get session key.")
        self.api_worker = None

    def auth_error(self, error_message):
        self.session_key = None
        self.status_label.setText("Status: Authentication Failed!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True) # Re-enable controls
        self.auth_button.setText("Re-authenticate")
        self.auth_button.setEnabled(True)
        self.api_worker = None
        QMessageBox.critical(self, "Authentication Error", error_message)


    # --- Search Logic ---
    def start_search_task(self):
        artist = self.search_artist_input.text().strip()
        track = self.search_track_input.text().strip()

        if not artist or not track:
            QMessageBox.warning(self, "Input Missing", "Please enter both Artist and Track name for search.")
            return

        self.status_label.setText(f"Status: Searching for '{track}' by '{artist}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False)
        self.search_results_list.clear()
        self.search_scrobble_button.setEnabled(False)

        # Run search in worker thread
        self.api_worker = ApiWorker(search_track, artist, track) # Use imported function
        self.api_worker.finished.connect(self.search_finished)
        self.api_worker.error.connect(self.search_error) # Use a generic error handler or specific one
        self.api_worker.start()

    def search_finished(self, results):
        self.set_controls_enabled(True)
        self.search_results_list.clear()

        if not results:
            self.status_label.setText("Status: Search returned no results.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.search_results_list.addItem("No results found.")
            self.search_scrobble_button.setEnabled(False)
        else:
            self.status_label.setText(f"Status: Found {len(results)} track(s). Double-click to use.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            for track_data in results:
                # Create a user-friendly string for the list item
                display_text = f"{track_data.get('name', 'N/A')} by {track_data.get('artist', 'N/A')}"
                item = QListWidgetItem(display_text)
                # Store the actual data within the item for later use
                item.setData(Qt.ItemDataRole.UserRole, track_data)
                self.search_results_list.addItem(item)
            # Enable scrobble button only if authenticated (selection handled separately)
            self.search_scrobble_button.setEnabled(bool(self.session_key))

        self.api_worker = None

    def search_error(self, error_message):
        self.status_label.setText("Status: Search Failed!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.search_scrobble_button.setEnabled(False)
        self.api_worker = None
        QMessageBox.critical(self, "Search Error", error_message)

    def populate_scrobble_from_search(self, item):
        track_data = item.data(Qt.ItemDataRole.UserRole)
        if track_data:
            self.artist_input.setText(track_data.get('artist', ''))
            self.track_input.setText(track_data.get('name', ''))
            # Try to find album info if available (might not be in search results)
            # If album info is needed reliably, a track.getInfo call might be necessary
            self.album_input.setText(track_data.get('album', '')) # Might be empty
            self.tabs.setCurrentWidget(self.scrobble_tab) # Switch to scrobble tab
            self.count_input.setValue(1) # Reset count on populate

    def scrobble_selected_search_result(self):
        selected_item = self.search_results_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Please select a track from the search results.")
            return

        track_data = selected_item.data(Qt.ItemDataRole.UserRole)
        if not track_data:
             QMessageBox.warning(self, "Error", "Could not retrieve data for the selected track.")
             return

        artist = track_data.get('artist')
        track = track_data.get('name')
        album = track_data.get('album') # Might be None or empty
        count = self.search_count_input.value()

        if not artist or not track:
             QMessageBox.warning(self, "Error", "Selected track data is incomplete.")
             return

        if count <= 0:
             QMessageBox.warning(self, "Invalid Count", "Scrobble count must be at least 1.")
             return

        tracks_to_scrobble = [{
            'artist': artist,
            'track': track,
            'album': album or None, # Ensure None if empty
            'count': count
        }]

        # Use the generic scrobble task starter
        self.start_scrobble_task(tracks_to_scrobble=tracks_to_scrobble)


    # --- Album Fetch Logic ---
    def start_fetch_album_tracks_task(self):
        artist = self.album_artist_input.text().strip()
        album = self.album_name_input.text().strip()

        if not artist or not album:
            QMessageBox.warning(self, "Input Missing", "Please enter both Artist and Album name.")
            return

        self.status_label.setText(f"Status: Fetching tracks for '{album}'...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during fetch
        self.album_tracks_list.clear()
        self.scrobble_album_button.setEnabled(False) # Disable scrobble btn until fetch complete

        # Store current artist/album for scrobbling later
        self.current_album_artist = artist
        self.current_album_name = album

        # Run fetch in worker thread
        self.api_worker = ApiWorker(get_album_tracks, artist, album) # Use imported function
        self.api_worker.finished.connect(self.album_tracks_finished)
        self.api_worker.error.connect(self.album_tracks_error)
        self.api_worker.start()

    def album_tracks_finished(self, track_list):
        self.set_controls_enabled(True) # Re-enable controls

        if track_list is None:
            # This means API call succeeded but album/tracks weren't found or list was empty
            self.status_label.setText(f"Status: Album '{self.current_album_name}' not found or has no tracks listed.")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            self.album_tracks_list.addItem("Album/Tracks not found.")
            self.scrobble_album_button.setEnabled(False)
            QMessageBox.warning(self, "Fetch Failed", f"Could not find tracks for album '{self.current_album_name}' by '{self.current_album_artist}'. Check spelling or Last.fm listing.")
        elif not track_list: # Empty list returned explicitly
             self.status_label.setText(f"Status: Found album '{self.current_album_name}' but it has no tracks listed.")
             self.status_label.setStyleSheet("color: orange; font-weight: bold;")
             self.album_tracks_list.addItem("No tracks listed for this album.")
             self.scrobble_album_button.setEnabled(False)
        else:
            self.status_label.setText(f"Status: Fetched {len(track_list)} tracks for '{self.current_album_name}'.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            for track_name in track_list:
                self.album_tracks_list.addItem(QListWidgetItem(track_name)) # Use QListWidgetItem
            # Enable scrobble button only if authenticated and tracks were found
            self.scrobble_album_button.setEnabled(bool(self.session_key))

        self.api_worker = None # Clear worker reference

    def album_tracks_error(self, error_message):
        self.status_label.setText("Status: Failed to fetch album tracks!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.scrobble_album_button.setEnabled(False)
        self.api_worker = None
        QMessageBox.critical(self, "Fetch Error", error_message)

    # --- Album Scrobble Logic ---
    def start_scrobble_album_task(self):
        if not self.session_key:
             QMessageBox.critical(self, "Error", "Not authenticated.")
             return

        if self.album_tracks_list.count() == 0 or self.album_tracks_list.item(0).text() in ["Album/Tracks not found.", "No tracks listed for this album."]:
            QMessageBox.warning(self, "No Tracks", "No tracks fetched to scrobble. Please fetch tracks first.")
            return

        artist = self.current_album_artist # Use stored artist/album
        album = self.current_album_name
        count_per_track = self.album_count_input.value()

        if not artist or not album:
             QMessageBox.critical(self, "Error", "Missing album artist or name. Please fetch tracks again.")
             return

        if count_per_track <= 0:
             QMessageBox.warning(self, "Invalid Count", "Scrobble count per track must be at least 1.")
             return

        tracks_to_scrobble = []
        for i in range(self.album_tracks_list.count()):
            track_item = self.album_tracks_list.item(i)
            track_name = track_item.text()
            tracks_to_scrobble.append({
                'artist': artist,
                'track': track_name,
                'album': album,
                'count': count_per_track
            })

        if not tracks_to_scrobble:
             QMessageBox.warning(self, "Error", "Could not prepare track list for scrobbling.")
             return

        # Use the existing generic scrobble task function
        self.start_scrobble_task(tracks_to_scrobble=tracks_to_scrobble)


    # --- Generic Scrobble Task Starter ---
    def start_scrobble_task(self, tracks_to_scrobble=None):
        if not self.session_key:
            QMessageBox.critical(self, "Error", "Not authenticated. Please authenticate first.")
            return

        if not tracks_to_scrobble: # If called from the manual scrobble tab
            artist = self.artist_input.text().strip()
            track = self.track_input.text().strip()
            album = self.album_input.text().strip() or None # Use None if empty
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
            return

        self.status_label.setText("Status: Scrobbliing...")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        self.set_controls_enabled(False) # Disable controls during scrobble

        # Setup and show progress dialog
        self.progress_dialog = QProgressDialog("Scrobbling...", "Cancel", 0, total_scrobbles, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(False) # Keep open until explicitly closed or cancelled
        self.progress_dialog.setAutoReset(False) # Keep value after finishing unless reset
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_task) # Connect cancel signal
        self.progress_dialog.show()


        # Run scrobbling in worker thread
        self.api_worker = ApiWorker(scrobble_multiple_tracks, # Use imported function
                                    tracks_info=tracks_to_scrobble,
                                    session_key=self.session_key,
                                    base_timestamp=int(time.time())) # Use current time as base
        self.api_worker.finished.connect(self.scrobble_finished)
        self.api_worker.error.connect(self.scrobble_error)
        self.api_worker.progress.connect(self.update_progress)
        self.api_worker.start()

    def scrobble_finished(self, result):
        if self.progress_dialog:
            self.progress_dialog.close() # Close progress dialog cleanly

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
        self.api_worker = None # Clear worker reference


    def scrobble_error(self, error_message):
        if self.progress_dialog:
            self.progress_dialog.close()
        self.status_label.setText("Status: Scrobble Failed!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.set_controls_enabled(True)
        self.api_worker = None
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
        if self.api_worker and self.api_worker.isRunning():
            print("Attempting to cancel task...")
            self.api_worker.requestInterruption() # Request interruption

            # Don't terminate forcefully here, let the thread finish if it can
            # The worker thread now checks self._is_interruption_requested

            self.status_label.setText("Status: Task Cancellation Requested")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # Re-enable controls immediately upon requesting cancel
            self.set_controls_enabled(True)
            if self.progress_dialog:
                self.progress_dialog.setLabelText("Cancelling...")
                # Don't close immediately, let the worker finish/error out if needed
                # self.progress_dialog.close() # Moved closing to finished/error handlers
            # Don't clear worker reference immediately, let signals fire
            # self.api_worker = None
            print("Task cancellation requested. Waiting for thread to acknowledge.")
        elif self.progress_dialog:
             # If progress dialog exists but worker doesn't (shouldn't happen often)
             self.progress_dialog.close()


    # --- Utility Functions ---
    def set_controls_enabled(self, enabled):
        is_authenticated = bool(self.session_key)
        has_search_results = self.search_results_list.count() > 0 and self.search_results_list.item(0).text() != "No results found."
        has_album_tracks = self.album_tracks_list.count() > 0 and self.album_tracks_list.item(0).text() not in ["Album/Tracks not found.", "No tracks listed for this album."]

        # General Auth Button
        # self.auth_button.setEnabled(enabled) # Keep auth button logic separate (handled in auth methods)

        # Scrobble Tab
        self.artist_input.setEnabled(enabled)
        self.track_input.setEnabled(enabled)
        self.album_input.setEnabled(enabled)
        self.count_input.setEnabled(enabled)
        self.scrobble_button.setEnabled(enabled and is_authenticated)

        # Search Tab
        self.search_artist_input.setEnabled(enabled)
        self.search_track_input.setEnabled(enabled)
        self.search_button.setEnabled(enabled)
        self.search_results_list.setEnabled(enabled)
        self.search_count_input.setEnabled(enabled and has_search_results)
        self.search_scrobble_button.setEnabled(enabled and is_authenticated and has_search_results and self.search_results_list.currentItem() is not None) # Enable only if item selected too

        # Album Tab
        self.album_artist_input.setEnabled(enabled)
        self.album_name_input.setEnabled(enabled)
        self.fetch_tracks_button.setEnabled(enabled and is_authenticated)
        self.album_tracks_list.setEnabled(enabled)
        self.album_count_input.setEnabled(enabled and has_album_tracks)
        self.scrobble_album_button.setEnabled(enabled and is_authenticated and has_album_tracks)

        # Re-enable search scrobble button based on selection change
        self.search_results_list.currentItemChanged.connect(
            lambda current, previous: self.search_scrobble_button.setEnabled(
                enabled and is_authenticated and has_search_results and current is not None
            )
        )


    def closeEvent(self, event):
        # Ensure worker thread is stopped if app closes
        if self.api_worker and self.api_worker.isRunning():
            print("Window closing, requesting task interruption...")
            self.cancel_task() # Try to clean up
            # Give it a moment to potentially stop
            self.api_worker.wait(500) # Wait half a second
            if self.api_worker and self.api_worker.isRunning():
                 print("Worker still running after wait, terminating forcefully.")
                 self.api_worker.terminate() # Force stop if still running (use cautiously)
                 self.api_worker.wait() # Wait for termination
        event.accept()


# --- Application Entry Point ---
if __name__ == '__main__':
    # Use imported variables for credential check
    if not all([API_KEY, API_SECRET, USERNAME, PASSWORD]):
        # Use a simple console message or a basic Tkinter/PyQt message box if preferred
        print("CRITICAL ERROR: Last.fm API credentials (API_KEY, API_SECRET, USERNAME, PASSWORD) not found in .env file or main.py.")
        print("Please create a .env file in the same directory with your credentials.")
        # Optionally show a GUI message box here if QApplication is already running
        # For simplicity, exiting here.
        sys.exit(1) # Exit if credentials aren't set

    app = QApplication(sys.argv)
    # Set Fusion style for a modern look
    app.setStyle('Fusion')
    ex = LastfmScrobblerApp()
    ex.show()
    sys.exit(app.exec())

