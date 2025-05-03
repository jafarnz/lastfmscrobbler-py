# Last.fm Mass Scrobbler (PyQt6)

A desktop application built with Python and PyQt6 to scrobble tracks and albums to your Last.fm profile.

## Features

*   **Manual Scrobble:** Scrobble a single track multiple times.
*   **Search & Scrobble:** Search for a track on Last.fm and scrobble the selected result multiple times.
*   **Album Scrobble:** Fetch all tracks from a specified album and scrobble each track a specified number of times.
*   **Authentication:** Securely authenticates with your Last.fm account using the mobile session method.
*   **Background Processing:** Uses QThread to perform API calls without freezing the GUI.
*   **Progress Indication:** Shows progress for batch scrobbling operations.

## Prerequisites

*   Python 3.x
*   A Last.fm account
*   Last.fm API Key and Secret (Get them [here](https://www.last.fm/api/account/create))

## Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/jafarnz/lastfmscrobbler-py.git
    cd lastfmscrobbler-py
    ```

2.  **Create a virtual environment (Recommended):**
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Create a `.env` file:**
    Create a file named `.env` in the project's root directory (`lastfmscrobbler-py`). Add your Last.fm API credentials and login details to this file:

    ```dotenv
    LASTFM_API_KEY=YOUR_API_KEY_HERE
    LASTFM_API_SECRET=YOUR_API_SECRET_HERE
    LASTFM_USERNAME=YOUR_LASTFM_USERNAME
    LASTFM_PASSWORD=YOUR_LASTFM_PASSWORD
    ```
    Replace the placeholder values with your actual credentials. **Do not commit this file to version control.** The included `.gitignore` file should prevent this automatically.

## Running the Application

Once the setup is complete, run the GUI script:

```bash
python gui.py
```

The application window should appear. It will attempt to authenticate automatically using the credentials in your `.env` file.

## Usage

1.  **Authentication:** The status label at the top will indicate if authentication was successful. If it fails, check your `.env` file and network connection.
2.  **Manual Scrobble:** Go to the "Single/Manual Scrobble" tab, enter the Artist, Track, Album (optional), and desired Scrobble Count, then click "Scrobble Track(s)".
3.  **Search & Scrobble:** Go to the "Search & Scrobble" tab, enter an Artist and Track, and click "Search Track". Double-click a result to populate the "Single/Manual Scrobble" tab, or select a result, set the "Scrobble Count" on the search tab, and click "Scrobble Selected Track".
4.  **Album Scrobble:** Go to the "Album Scrobble" tab, enter the Artist and Album name, and click "Fetch Album Tracks". Once the tracklist appears, set the "Scrobbles per Track" and click "Scrobble Entire Album".

**Note:** The application includes delays between scrobble requests to avoid hitting Last.fm API rate limits too quickly. Be mindful of Last.fm's terms of service regarding API usage.
