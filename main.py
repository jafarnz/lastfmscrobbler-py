# Last.fm API Logic Module

import os
import time
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

API_KEY = os.getenv('LASTFM_API_KEY')
API_SECRET = os.getenv('LASTFM_API_SECRET')
USERNAME = os.getenv('LASTFM_USERNAME')
PASSWORD = os.getenv('LASTFM_PASSWORD')

API_URL = 'http://ws.audioscrobbler.com/2.0/'

# --- Helper Functions ---

def _get_api_signature(params):
    """Generates the API signature required by Last.fm."""
    sorted_params = sorted(params.items())
    param_string = "".join([f"{k}{v}" for k, v in sorted_params])
    param_string += API_SECRET
    return hashlib.md5(param_string.encode('utf-8')).hexdigest()

def _make_api_request(method, http_method='GET', params=None, requires_signature=False, requires_session=False, session_key=None):
    """Makes a generic request to the Last.fm API."""
    if params is None:
        params = {}

    # Parameters that will be sent in the final request
    request_params = params.copy()
    request_params['method'] = method
    request_params['api_key'] = API_KEY

    # Parameters used ONLY for signature calculation (exclude 'format')
    signature_params = request_params.copy()

    if requires_session:
        if not session_key:
            raise ValueError("Session key is required for this method.")
        # Session key is part of the signature AND the request
        request_params['sk'] = session_key
        signature_params['sk'] = session_key

    if requires_signature:
        if not API_SECRET:
             raise ValueError("API Secret is required for signed methods.")
        # Calculate signature using only the required parameters
        request_params['api_sig'] = _get_api_signature(signature_params)

    # Add 'format' parameter AFTER signature calculation
    request_params['format'] = 'json'

    try:
        if http_method.upper() == 'POST':
            # Use request_params which now includes api_sig and format
            response = requests.post(API_URL, data=request_params)
        else: # Default to GET
            # Use request_params which now includes api_sig and format
            response = requests.get(API_URL, params=request_params)

        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Check for empty response before trying to decode JSON
        if not response.text:
            # Handle cases where API might return empty success (though unlikely for JSON format)
            # Or treat as an error depending on context
            print(f"Warning: Received empty response for method {method}")
            return None # Or raise an exception

        data = response.json()

        # Check for Last.fm specific errors within the JSON response
        if 'error' in data:
            raise LastfmApiError(data.get('error'), data.get('message', 'Unknown API error'))

        return data

    except requests.exceptions.RequestException as e:
        # Handle network errors, timeouts, etc.
        raise LastfmApiError(code=None, message=f"Network error during API request: {e}") from e
    except ValueError as e:
        # Handle JSON decoding errors
        raise LastfmApiError(code=None, message=f"Error decoding API response: {response.text}") from e


# --- Custom Exception ---
class LastfmApiError(Exception):
    """Custom exception for Last.fm API errors."""
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"Last.fm API Error {code}: {message}")


# --- Core API Functions ---

def get_session_key():
    """Authenticates with Last.fm and retrieves a session key."""
    if not all([API_KEY, API_SECRET, USERNAME, PASSWORD]):
        raise ValueError("API Key, Secret, Username, and Password must be set in .env")

    auth_params = {
        'username': USERNAME,
        'password': PASSWORD,
    }
    # Note: getMobileSession requires API signature
    try:
        data = _make_api_request('auth.getMobileSession', http_method='POST', params=auth_params, requires_signature=True)
        if data and 'session' in data and 'key' in data['session']:
            return data['session']['key']
        else:
            # This path might be less likely now due to error checking in _make_api_request
            raise LastfmApiError(code=None, message=f"Authentication failed. Response: {data}")
    except LastfmApiError as e:
        # Re-raise specific auth errors for clarity
        raise LastfmApiError(code=e.code, message=f"Authentication failed: {e.message}")


def search_track(artist, track):
    """Searches for a track on Last.fm. Returns a list of track results."""
    search_params = {
        'artist': artist,
        'track': track,
        'limit': 10 # Limit results for GUI display
    }
    try:
        data = _make_api_request('track.search', params=search_params)
        if (data and 'results' in data and
            'trackmatches' in data['results'] and
            'track' in data['results']['trackmatches']):

            tracks_data = data['results']['trackmatches']['track']
            # Ensure tracks_data is always a list
            if isinstance(tracks_data, dict):
                return [tracks_data] # Wrap single track in a list
            elif isinstance(tracks_data, list):
                return tracks_data
            else:
                return [] # No tracks found
        else:
            return [] # No results structure found
    except LastfmApiError as e:
        print(f"Error during track search: {e}") # Log or handle differently in GUI
        return [] # Return empty list on error for search


def get_album_tracks(artist, album):
    """Fetches track list for a given album. Returns a list of track names."""
    album_params = {
        'artist': artist,
        'album': album,
    }
    try:
        data = _make_api_request('album.getInfo', params=album_params)
        if (data and 'album' in data and
            'tracks' in data['album'] and
            'track' in data['album']['tracks']):

            tracks_data = data['album']['tracks']['track']
            if isinstance(tracks_data, dict):
                tracks_data = [tracks_data] # Wrap single track

            track_list = [track['name'] for track in tracks_data if 'name' in track]
            return track_list
        else:
            # Album might exist but have no tracks listed, or album not found
            # The API error for "not found" should be caught by LastfmApiError
            return None # Indicate album found but no tracks, or other non-error issue
    except LastfmApiError as e:
        # Handle specific errors like "Album not found" (error code 6)
        if e.code == 6:
            print(f"Album '{album}' by '{artist}' not found.")
        else:
            print(f"Error fetching album info: {e}")
        return None # Return None on error


def scrobble_track(artist, track, timestamp, session_key, album=None):
    """Scrobbles a single track to Last.fm. Returns True on success, False on failure."""
    if not session_key:
        raise ValueError("Session key is required to scrobble.")

    scrobble_params = {
        'artist[0]': artist,
        'track[0]': track,
        'timestamp[0]': timestamp,
    }
    if album:
        scrobble_params['album[0]'] = album

    try:
        data = _make_api_request('track.scrobble', http_method='POST', params=scrobble_params, requires_signature=True, requires_session=True, session_key=session_key)

        # Check response structure for scrobbles array and acceptance attribute
        if data and 'scrobbles' in data:
            scrobble_info = data['scrobbles']
            # Handle cases where response might be dict ('scrobble') or list ('@attr')
            if isinstance(scrobble_info, dict) and 'scrobble' in scrobble_info:
                 # Check inner structure if needed, assume success for now
                 return True
            elif isinstance(scrobble_info, dict) and '@attr' in scrobble_info and scrobble_info['@attr'].get('accepted', 0) == 1:
                 return True
            elif isinstance(scrobble_info, dict) and '@attr' in scrobble_info and scrobble_info['@attr'].get('ignored', 0) == 1:
                 ignored_code = scrobble_info['scrobble']['ignoredMessage'].get('code', 'N/A')
                 ignored_msg = scrobble_info['scrobble']['ignoredMessage'].get('#text', 'Ignored')
                 print(f"Scrobble ignored ({ignored_code}): {ignored_msg} for track '{track}'")
                 return False # Treat ignored as failure for our purpose

        # If structure isn't as expected or not accepted/ignored
        print(f"Failed to scrobble '{track}' by '{artist}'. Unexpected Response: {data}")
        return False

    except LastfmApiError as e:
        print(f"Error during scrobble request: {e}")
        return False

# --- Batch Scrobbling Helper ---

def scrobble_multiple_tracks(tracks_info, session_key, base_timestamp=None, delay_seconds=0.2, progress_callback=None):
    """
    Scrobbles a list of tracks with specified counts and timestamps.

    Args:
        tracks_info (list): A list of dictionaries, each containing:
                            {'artist': str, 'track': str, 'album': str|None, 'count': int}
        session_key (str): The authenticated session key.
        base_timestamp (int, optional): The timestamp for the *most recent* scrobble.
                                        Older scrobbles will be calculated relative to this.
                                        Defaults to current time.
        delay_seconds (float): Delay between individual scrobble API calls.
        progress_callback (callable, optional): A function to call for progress updates.
                                                It receives (current_count, total_count, message).

    Returns:
        tuple: (success_count, failure_count)
    """
    if base_timestamp is None:
        base_timestamp = int(time.time())

    total_scrobbles_to_send = sum(info.get('count', 0) for info in tracks_info)
    if total_scrobbles_to_send == 0:
        return 0, 0

    print(f"Preparing to send {total_scrobbles_to_send} scrobbles...")

    scrobbles_sent_total = 0
    failed_scrobbles_total = 0
    timestamp_offset = 0 # Increments for each scrobble sent

    for track_info in tracks_info:
        artist = track_info['artist']
        track = track_info['track']
        album = track_info.get('album') # Optional
        count = track_info.get('count', 0)

        if count <= 0:
            continue

        print(f"\nScrobbling '{track}' by '{artist}' ({count} times)")
        scrobbles_sent_this_track = 0

        for i in range(count):
            # Calculate timestamp for this specific scrobble (going backwards in time)
            timestamp_to_use = base_timestamp - (timestamp_offset * 60) # 1 minute apart seems reasonable
            timestamp_offset += 1

            success = scrobble_track(artist, track, timestamp_to_use, session_key, album=album)

            if success:
                scrobbles_sent_total += 1
                scrobbles_sent_this_track += 1
            else:
                failed_scrobbles_total += 1
                # Log failure, maybe add retry later
                print(f"  Failed attempt {i+1}/{count} for '{track}'")
                time.sleep(1) # Longer delay after failure

            # Progress update
            progress_message = f"Track: {scrobbles_sent_this_track}/{count} | Total: {scrobbles_sent_total}/{total_scrobbles_to_send}"
            print(f"  {progress_message}", end='\r')
            if progress_callback:
                try:
                    progress_callback(scrobbles_sent_total, total_scrobbles_to_send, progress_message)
                except Exception as cb_err:
                    print(f"\nError in progress callback: {cb_err}") # Don't let callback crash scrobbling

            # Delay between all requests
            time.sleep(delay_seconds)

        print() # Newline after finishing a track's scrobbles

    print(f"\nFinished. Sent: {scrobbles_sent_total}, Failed: {failed_scrobbles_total}")
    return scrobbles_sent_total, failed_scrobbles_total


# Example usage (for testing the module directly, remove in final GUI app)
# if __name__ == "__main__":
#     try:
#         print("Attempting authentication...")
#         sk = get_session_key()
#         print(f"Session Key obtained: {sk[:5]}...") # Don't print full key normally

#         # Test Search
#         print("\nTesting track search...")
#         results = search_track("Pink Floyd", "Comfortably Numb")
#         if results:
#             print(f"Found {len(results)} results for 'Comfortably Numb':")
#             for r in results[:3]: # Print top 3
#                 print(f" - {r.get('name')} by {r.get('artist')}")
#         else:
#             print("Search returned no results.")

#         # Test Album Info
#         print("\nTesting album info...")
#         tracks = get_album_tracks("Pink Floyd", "The Wall")
#         if tracks:
#             print(f"Found {len(tracks)} tracks on 'The Wall':")
#             print(f"  First few: {tracks[:5]}")
#         else:
#             print("Could not get tracks for 'The Wall'.")

#         # Test Scrobble (Use with caution!)
#         # print("\nTesting scrobble...")
#         # current_ts = int(time.time())
#         # success = scrobble_track("Test Artist", "Test Track", current_ts - 600, sk, album="Test Album")
#         # print(f"Scrobble success: {success}")

#         # Test Batch Scrobble (Use with extreme caution!)
#         # print("\nTesting batch scrobble...")
#         # tracks_to_batch = [
#         #     {'artist': 'Test Batch Artist', 'track': 'Batch Track 1', 'album': 'Batch Album', 'count': 2},
#         #     {'artist': 'Test Batch Artist', 'track': 'Batch Track 2', 'album': 'Batch Album', 'count': 1},
#         # ]
#         # sent, failed = scrobble_multiple_tracks(tracks_to_batch, sk)
#         # print(f"Batch result: Sent={sent}, Failed={failed}")


#     except ValueError as e:
#         print(f"Configuration Error: {e}")
#     except LastfmApiError as e:
#         print(f"API Error: {e}")
#     except Exception as e:
#         print(f"An unexpected error occurred: {e}")