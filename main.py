# Last.fm API Logic Module

import os
import time
import hashlib
import requests
from dotenv import load_dotenv
import requests_cache

load_dotenv() # Load environment variables from .env file

API_KEY = os.getenv('LASTFM_API_KEY')
API_SECRET = os.getenv('LASTFM_API_SECRET')
USERNAME = os.getenv('LASTFM_USERNAME')
PASSWORD = os.getenv('LASTFM_PASSWORD')

API_URL = 'http://ws.audioscrobbler.com/2.0/'

# --- Cache Setup ---
# Cache API responses for 1 hour to reduce load and speed up repeated requests
requests_cache.install_cache('lastfm_cache', backend='sqlite', expire_after=3600)
print("Requests caching enabled.")

# --- Helper Functions ---

def _get_api_signature(params):
    """Generates the API signature required by Last.fm."""
    sorted_params = sorted(params.items())
    param_string = "".join([f"{k}{v}" for k, v in sorted_params])
    param_string += API_SECRET
    return hashlib.md5(param_string.encode('utf-8')).hexdigest()

def _extract_image_url(image_data, size_preference=['extralarge', 'large', 'medium', 'small']):
    """Extracts the best available image URL from Last.fm image data."""
    if not isinstance(image_data, list):
        return None
    image_urls = {img['size']: img.get('#text') for img in image_data if '#text' in img and img.get('#text')}
    for size in size_preference:
        if size in image_urls:
            return image_urls[size]
    # Fallback to the first available URL if preferred sizes are not found
    if image_urls:
        return next(iter(image_urls.values()))
    return None

def _make_api_request(method, http_method='GET', params=None, requires_signature=False, requires_session=False, session_key=None):
    """Makes a generic request to the Last.fm API (now cached)."""
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
            # For POST requests that modify data (like scrobble), bypass cache
            with requests_cache.disabled():
                 response = requests.post(API_URL, data=request_params)
        else: # Default to GET
            # Use request_params which now includes api_sig and format
            # GET requests will use the installed cache automatically
            response = requests.get(API_URL, params=request_params)

        # Check cache status (optional, for debugging)
        # print(f"Cache used for {method}: {getattr(response, 'from_cache', False)}")

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
        # Check if the request was from cache; if so, the cache file might be corrupted
        is_from_cache = getattr(locals().get('response'), 'from_cache', False)
        error_message = f"Network error during API request: {e}"
        if is_from_cache:
            error_message += " (Request was from cache, cache might be corrupted)"
        raise LastfmApiError(code=None, message=error_message) from e
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
        # Authentication should not be cached
        with requests_cache.disabled():
            data = _make_api_request('auth.getMobileSession', http_method='POST', params=auth_params, requires_signature=True)
        if data and 'session' in data and 'key' in data['session']:
            return data['session']['key']
        else:
            # This path might be less likely now due to error checking in _make_api_request
            raise LastfmApiError(code=None, message=f"Authentication failed. Response: {data}")
    except LastfmApiError as e:
        # Re-raise specific auth errors for clarity
        raise LastfmApiError(code=e.code, message=f"Authentication failed: {e.message}")


def search_track(artist=None, track=None):
    """
    Searches for a track on Last.fm. Returns a list of track result dictionaries, including image URL.
    Either artist or track parameter can be provided alone for more dynamic searches.
    """
    search_params = {
        'limit': 15  # Increased limit for more results
    }
    
    # Add parameters only if they're provided
    if artist and artist.strip():
        search_params['artist'] = artist.strip()
    
    if track and track.strip():
        search_params['track'] = track.strip()
        
    # At least one parameter should be provided
    if not search_params.get('artist') and not search_params.get('track'):
        return []
    
    try:
        data = _make_api_request('track.search', params=search_params)
        if (data and 'results' in data and
            'trackmatches' in data['results'] and
            'track' in data['results']['trackmatches']):

            tracks_data = data['results']['trackmatches']['track']
            # Ensure tracks_data is always a list
            if isinstance(tracks_data, dict):
                tracks_data = [tracks_data]  # Wrap single track in a list
            elif not isinstance(tracks_data, list):
                 tracks_data = [] # No tracks found or unexpected format

            # Extract relevant info, including image
            results = []
            for t in tracks_data:
                results.append({
                    'name': t.get('name'),
                    'artist': t.get('artist'),
                    'url': t.get('url'),
                    'listeners': t.get('listeners'),
                    'image_url': _extract_image_url(t.get('image'))
                })
            return results
        else:
            return []  # No results structure found
    except LastfmApiError as e:
        print(f"Error during track search: {e}")  # Log or handle differently in GUI
        return []  # Return empty list on error for search


def get_album_tracks(artist, album):
    """Fetches track list for a given album. Returns a list of track names."""
    # Use get_album_info instead to get image and more details
    album_info = get_album_info(artist, album)
    if album_info and 'tracks' in album_info and 'track' in album_info['tracks']:
        tracks_data = album_info['tracks']['track']
        if isinstance(tracks_data, dict):
            tracks_data = [tracks_data] # Wrap single track

        track_list = [track['name'] for track in tracks_data if 'name' in track]
        return track_list
    else:
        return None # Indicate album found but no tracks, or other non-error issue


def get_track_info(artist, track):
    """Gets detailed information about a specific track, including album title and image."""
    track_params = {
        'artist': artist,
        'track': track,
    }
    try:
        data = _make_api_request('track.getInfo', params=track_params)
        if data and 'track' in data:
            track_details = data['track']
            album_info = track_details.get('album')
            # Extract info safely
            result = {
                'name': track_details.get('name'),
                'artist': track_details.get('artist', {}).get('name'), # Artist info is nested
                'url': track_details.get('url'),
                'duration': track_details.get('duration'), # Often 0 if unknown
                'listeners': track_details.get('listeners'),
                'playcount': track_details.get('playcount'),
                'album_title': album_info.get('title') if album_info else None,
                'album_artist': album_info.get('artist') if album_info else None, # Usually same as track artist
                'image_url': _extract_image_url(album_info.get('image')) if album_info else _extract_image_url(track_details.get('image')), # Prefer album art
                'tags': [tag.get('name') for tag in track_details.get('toptags', {}).get('tag', [])],
                'wiki': track_details.get('wiki', {}).get('content') # Track wiki/bio
            }
            return result
        else:
            return None
    except LastfmApiError as e:
        print(f"Error getting track info: {e}")
        return None


def search_artist(artist_name):
    """
    Search for an artist on Last.fm.
    Returns a list of artist dicts including name, image URLs, and listener stats.
    """
    search_params = {
        'artist': artist_name,
        'limit': 10
    }
    try:
        data = _make_api_request('artist.search', params=search_params)
        if (data and 'results' in data and
            'artistmatches' in data['results'] and
            'artist' in data['results']['artistmatches']):
            
            artists_data = data['results']['artistmatches']['artist']
            if isinstance(artists_data, dict):
                artists_data = [artists_data]  # Wrap single artist in a list
            elif not isinstance(artists_data, list):
                artists_data = []

            results = []
            for a in artists_data:
                 results.append({
                    'name': a.get('name'),
                    'listeners': a.get('listeners'),
                    'mbid': a.get('mbid'), # MusicBrainz ID
                    'url': a.get('url'),
                    'image_url': _extract_image_url(a.get('image'))
                 })
            return results
        else:
            return []
    except LastfmApiError as e:
        print(f"Error during artist search: {e}")
        return []


def get_artist_info(artist_name):
    """
    Get detailed information about an artist including bio, similar artists, tags, image etc.
    """
    artist_params = {
        'artist': artist_name
    }
    try:
        data = _make_api_request('artist.getInfo', params=artist_params)
        if data and 'artist' in data:
            artist_details = data['artist']
            result = {
                 'name': artist_details.get('name'),
                 'mbid': artist_details.get('mbid'),
                 'url': artist_details.get('url'),
                 'image_url': _extract_image_url(artist_details.get('image')),
                 'listeners': artist_details.get('stats', {}).get('listeners'),
                 'playcount': artist_details.get('stats', {}).get('playcount'),
                 'similar_artists': [sim_art.get('name') for sim_art in artist_details.get('similar', {}).get('artist', [])],
                 'tags': [tag.get('name') for tag in artist_details.get('tags', {}).get('tag', [])],
                 'bio_summary': artist_details.get('bio', {}).get('summary'),
                 'bio_content': artist_details.get('bio', {}).get('content')
            }
            return result
        else:
            return None
    except LastfmApiError as e:
        print(f"Error getting artist info: {e}")
        return None


def get_artist_top_tracks(artist_name, limit=10):
    """
    Get the top tracks for an artist, including image URL (usually album art).
    """
    track_params = {
        'artist': artist_name,
        'limit': limit
    }
    try:
        data = _make_api_request('artist.getTopTracks', params=track_params)
        if data and 'toptracks' in data and 'track' in data['toptracks']:
            tracks_data = data['toptracks']['track']
            if isinstance(tracks_data, dict):
                tracks_data = [tracks_data] # Wrap single track
            elif not isinstance(tracks_data, list):
                 tracks_data = []

            results = []
            for t in tracks_data:
                 results.append({
                     'name': t.get('name'),
                     'playcount': t.get('playcount'),
                     'listeners': t.get('listeners'),
                     'mbid': t.get('mbid'),
                     'url': t.get('url'),
                     'artist': t.get('artist', {}).get('name'), # Artist info nested
                     'image_url': _extract_image_url(t.get('image'))
                 })
            return results
        else:
            return []
    except LastfmApiError as e:
        print(f"Error getting top tracks: {e}")
        return []


def get_artist_albums(artist_name, limit=20):
    """
    Get the top albums for an artist, including image URL.
    """
    album_params = {
        'artist': artist_name,
        'limit': limit
    }
    try:
        data = _make_api_request('artist.getTopAlbums', params=album_params)
        if data and 'topalbums' in data and 'album' in data['topalbums']:
            albums_data = data['topalbums']['album']
            if isinstance(albums_data, dict):
                albums_data = [albums_data] # Wrap single album
            elif not isinstance(albums_data, list):
                 albums_data = []

            results = []
            for a in albums_data:
                 results.append({
                    'name': a.get('name'),
                    'playcount': a.get('playcount'),
                    'mbid': a.get('mbid'),
                    'url': a.get('url'),
                    'artist': a.get('artist', {}).get('name'), # Artist info nested
                    'image_url': _extract_image_url(a.get('image'))
                 })
            return results
        else:
            return []
    except LastfmApiError as e:
        print(f"Error getting artist albums: {e}")
        return []


def get_album_info(artist, album):
    """
    Get detailed information about an album including tracks, release date, cover art, tags, wiki.
    """
    album_params = {
        'artist': artist,
        'album': album
    }
    try:
        data = _make_api_request('album.getInfo', params=album_params)
        if data and 'album' in data:
            album_details = data['album']
            result = {
                'name': album_details.get('name'),
                'artist': album_details.get('artist'),
                'mbid': album_details.get('mbid'),
                'url': album_details.get('url'),
                'image_url': _extract_image_url(album_details.get('image')),
                'listeners': album_details.get('listeners'),
                'playcount': album_details.get('playcount'),
                'release_date': album_details.get('wiki', {}).get('published'), # Often in wiki
                'tags': [tag.get('name') for tag in album_details.get('tags', {}).get('tag', [])],
                'wiki_summary': album_details.get('wiki', {}).get('summary'),
                'wiki_content': album_details.get('wiki', {}).get('content'),
                'tracks': [{ # Extract basic track info here too
                    'name': track.get('name'),
                    'duration': track.get('duration'), # Sometimes available
                    'url': track.get('url'),
                    '@attr': track.get('@attr', {}) # Contains rank
                 } for track in album_details.get('tracks', {}).get('track', [])]

            }
            # Ensure tracks is always a list, even if API returns single item not in list
            if 'tracks' in album_details and 'track' in album_details['tracks'] and isinstance(album_details['tracks']['track'], dict):
                 result['tracks'] = [result['tracks'][0]] # Wrap the single track dict


            return result
        else:
            return None
    except LastfmApiError as e:
        # Handle specific errors like "Album not found" (error code 6)
        if e.code == 6:
            print(f"Album '{album}' by '{artist}' not found.") # Keep console message for now
        else:
            print(f"Error getting album info: {e}")
        return None # Return None on error or not found


# --- Batch Scrobbling Helper ---
def scrobble_multiple_tracks(tracks_info, session_key, base_timestamp=None, delay_seconds=0.1, progress_callback=None):
    """
    Scrobbles a list of tracks using batch requests (up to 50 per request).

    Args:
        tracks_info (list): A list of dictionaries, each containing:
                            {'artist': str, 'track': str, 'album': str|None, 'count': int}
        session_key (str): The authenticated session key.
        base_timestamp (int, optional): Timestamp for the *most recent* scrobble.
                                        Defaults to current time.
        delay_seconds (float): Delay between batch API calls.
        progress_callback (callable, optional): Receives (current_count, total_count, message).

    Returns:
        tuple: (success_count, failure_count)
    """
    if not session_key:
        raise ValueError("Session key is required to scrobble.")
    if base_timestamp is None:
        base_timestamp = int(time.time())

    all_scrobbles = []
    total_scrobbles_to_send = 0
    timestamp_offset = 0 # Increments for each individual scrobble generated

    # 1. Generate flat list of all individual scrobbles with timestamps
    for track_info in tracks_info:
        count = track_info.get('count', 0)
        if count <= 0:
            continue
        total_scrobbles_to_send += count
        for _ in range(count):
            # Calculate timestamp for this specific scrobble (going backwards in time)
            # Spread timestamps slightly (e.g., 60 seconds apart)
            timestamp_to_use = base_timestamp - timestamp_offset * 60
            timestamp_offset += 1
            all_scrobbles.append({
                'artist': track_info['artist'],
                'track': track_info['track'],
                'album': track_info.get('album'),
                'timestamp': timestamp_to_use
            })

    if not all_scrobbles:
        print("No tracks to scrobble.")
        return 0, 0

    print(f"Preparing to send {total_scrobbles_to_send} scrobbles in batches...")
    scrobbles_sent_total = 0
    failed_scrobbles_total = 0
    processed_count = 0
    batch_size = 50

    # 2. Group into chunks and send batch requests
    for i in range(0, len(all_scrobbles), batch_size):
        batch = all_scrobbles[i:i + batch_size]
        batch_params = {}
        print(f"Sending batch {i // batch_size + 1}/{(len(all_scrobbles) + batch_size - 1) // batch_size} ({len(batch)} tracks)")

        # Construct parameters for the batch
        for idx, scrobble in enumerate(batch):
            batch_params[f'artist[{idx}]'] = scrobble['artist']
            batch_params[f'track[{idx}]'] = scrobble['track']
            batch_params[f'timestamp[{idx}]'] = scrobble['timestamp']
            if scrobble['album']:
                batch_params[f'album[{idx}]'] = scrobble['album']

        try:
            # Make the batch API request
            data = _make_api_request('track.scrobble', http_method='POST', params=batch_params, requires_signature=True, requires_session=True, session_key=session_key)

            # 3. Parse Batch Response
            accepted_count = 0
            ignored_count = 0
            if data and 'scrobbles' in data:
                scrobbles_attr = data['scrobbles'].get('@attr', {})
                accepted_count = int(scrobbles_attr.get('accepted', 0))
                ignored_count = int(scrobbles_attr.get('ignored', 0))
                # Note: The detailed ignored messages per track aren't easily accessible here without complex parsing
                if ignored_count > 0:
                     print(f"  Batch {i // batch_size + 1}: {ignored_count} scrobbles ignored (check Last.fm profile for details).")

            scrobbles_sent_total += accepted_count
            failed_scrobbles_total += ignored_count
            processed_count += len(batch) # Update progress based on tracks processed in the batch

            print(f"  Batch {i // batch_size + 1}: Accepted: {accepted_count}, Ignored: {ignored_count}")

        except LastfmApiError as e:
            print(f"ERROR during scrobble batch {i // batch_size + 1}: {e}")
            failed_scrobbles_total += len(batch) # Assume all in batch failed on API error
            processed_count += len(batch)
            # Add a longer delay after a batch error
            time.sleep(2)
        except Exception as e:
            print(f"UNEXPECTED ERROR during scrobble batch {i // batch_size + 1}: {e}")
            failed_scrobbles_total += len(batch)
            processed_count += len(batch)
            time.sleep(2)

        # 4. Update Progress Callback
        progress_message = f"Batch {i // batch_size + 1} done | Processed: {processed_count}/{total_scrobbles_to_send}"
        if progress_callback:
            try:
                progress_callback(processed_count, total_scrobbles_to_send, progress_message)
            except InterruptedError: # Catch interruption from callback
                raise # Re-raise to stop the loop
            except Exception as cb_err:
                print(f"\nError in progress callback: {cb_err}")

        # Delay between batch requests
        if i + batch_size < len(all_scrobbles):
             time.sleep(delay_seconds)

    print(f"\nFinished. Accepted: {scrobbles_sent_total}, Failed/Ignored: {failed_scrobbles_total}")
    return scrobbles_sent_total, failed_scrobbles_total