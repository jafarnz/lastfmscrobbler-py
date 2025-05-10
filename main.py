# Last.fm API Logic Module

import os
import time
import hashlib
import requests
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any

load_dotenv() # Load environment variables from .env file

# Default values that will be updated by the login dialog
API_KEY = ""
API_SECRET = ""
USERNAME = ""
PASSWORD = ""

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

def get_session_key_from_credentials():
    """Get session key directly using the stored credentials"""
    if not API_KEY or not API_SECRET or not USERNAME or not PASSWORD:
        raise ValueError("API key, API secret, username, and password are required")
        
    # Create signature for auth.getMobileSession
    sig = hashlib.md5(
        f'api_key{API_KEY}methodauth.getMobileSessionpassword{PASSWORD}username{USERNAME}{API_SECRET}'.encode()
    ).hexdigest()
    
    params = {
        'method': 'auth.getMobileSession',
        'api_key': API_KEY,
        'username': USERNAME,
        'password': PASSWORD,
        'api_sig': sig,
        'format': 'json'
    }
    
    response = requests.post('https://ws.audioscrobbler.com/2.0/', data=params)
    data = response.json()
    
    if 'error' in data:
        raise Exception(f"Failed to get session key: {data.get('message', 'Unknown error')}")
    
    if 'session' not in data:
        raise Exception(f"Failed to get session key: Response missing session data")
    
    return data['session']['key']

def get_auth_token() -> str:
    """Get authentication token from Last.fm"""
    params = {
        'method': 'auth.getToken',
        'api_key': API_KEY,
        'format': 'json'
    }
    
    response = requests.get('https://ws.audioscrobbler.com/2.0/', params=params)
    data = response.json()
    
    if 'token' not in data:
        raise Exception(f"Failed to get auth token: {data.get('message', 'Unknown error')}")
    
    return data['token']

def get_session_key(token: str) -> str:
    """Get session key using the auth token"""
    # Create the signature
    sig = hashlib.md5(
        f'api_key{API_KEY}methodauth.getSessiontoken{token}{API_SECRET}'.encode()
    ).hexdigest()
    
    params = {
        'method': 'auth.getSession',
        'api_key': API_KEY,
        'token': token,
        'api_sig': sig,
        'format': 'json'
    }
    
    response = requests.get('https://ws.audioscrobbler.com/2.0/', params=params)
    data = response.json()
    
    if 'session' not in data:
        raise Exception(f"Failed to get session key: {data.get('message', 'Unknown error')}")
    
    return data['session']['key']

def search_track(artist=None, track=None):
    """
    Searches for a track on Last.fm. Returns a list of track results.
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
                return [tracks_data]  # Wrap single track in a list
            elif isinstance(tracks_data, list):
                return tracks_data
            else:
                return []  # No tracks found
        else:
            return []  # No results structure found
    except LastfmApiError as e:
        print(f"Error during track search: {e}")  # Log or handle differently in GUI
        return []  # Return empty list on error for search


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
        return False
    except LastfmApiError as e:
        print(f"Error during scrobble request: {e}")
        return False


def get_track_info(artist, track):
    """Gets detailed information about a specific track from Last.fm API."""
    track_params = {
        'artist': artist,
        'track': track,
    }
    try:
        data = _make_api_request('track.getInfo', params=track_params)
        if data and 'track' in data:
            track_data = data['track']
            
            # Create a standardized response structure
            result = {
                'name': track_data.get('name', track),
                'artist': track_data.get('artist', artist) if isinstance(track_data.get('artist'), str) else
                          track_data.get('artist', {}).get('name', artist),
                'album_title': None,
                'image_url': None
            }
            
            # Extract album information if available
            if 'album' in track_data and isinstance(track_data['album'], dict):
                result['album_title'] = track_data['album'].get('title')
                
                # Get album image if available
                if 'image' in track_data['album']:
                    for img in track_data['album']['image']:
                        if img['size'] == 'large' and img.get('#text'):
                            result['image_url'] = img['#text']
                            break
            
            # If no album image, try track image
            if not result['image_url'] and 'image' in track_data:
                for img in track_data['image']:
                    if img['size'] == 'large' and img.get('#text'):
                        result['image_url'] = img['#text']
                        break
            
            return result
        else:
            return None
    except LastfmApiError as e:
        print(f"Error getting track info: {e}")
        return None


def search_artist(artist_name):
    """
    Search for an artist on Last.fm.
    Returns artist information including name, image URLs, and listener stats.
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
                return [artists_data]  # Wrap single artist in a list
            elif isinstance(artists_data, list):
                return artists_data
            else:
                return []
        else:
            return []
    except LastfmApiError as e:
        print(f"Error during artist search: {e}")
        return []


def get_artist_info(artist_name):
    """
    Get detailed information about an artist including bio, similar artists, tags, etc.
    """
    artist_params = {
        'artist': artist_name
    }
    try:
        data = _make_api_request('artist.getInfo', params=artist_params)
        if data and 'artist' in data:
            return data['artist']
        else:
            return None
    except LastfmApiError as e:
        print(f"Error getting artist info: {e}")
        return None


def get_artist_top_tracks(artist_name, limit=10):
    """
    Get the top tracks for an artist.
    """
    track_params = {
        'artist': artist_name,
        'limit': limit
    }
    try:
        data = _make_api_request('artist.getTopTracks', params=track_params)
        if data and 'toptracks' in data and 'track' in data['toptracks']:
            tracks = data['toptracks']['track']
            if isinstance(tracks, dict):
                return [tracks]
            elif isinstance(tracks, list):
                return tracks
            else:
                return []
        else:
            return []
    except LastfmApiError as e:
        print(f"Error getting top tracks: {e}")
        return []


def get_artist_albums(artist_name, limit=20):
    """
    Get the albums from an artist.
    """
    album_params = {
        'artist': artist_name,
        'limit': limit
    }
    try:
        data = _make_api_request('artist.getTopAlbums', params=album_params)
        if data and 'topalbums' in data and 'album' in data['topalbums']:
            albums = data['topalbums']['album']
            if isinstance(albums, dict):
                return [albums]
            elif isinstance(albums, list):
                return albums
            else:
                return []
        else:
            return []
    except LastfmApiError as e:
        print(f"Error getting artist albums: {e}")
        return []


def get_album_info(artist, album):
    """Fetches full album information including tracks and image URLs."""
    album_params = {
        'artist': artist,
        'album': album,
        # 'autocorrect': 1 # Consider if autocorrect is desired
    }
    try:
        data = _make_api_request('album.getInfo', params=album_params)
        if data and 'album' in data:
            album_details = data['album']
            # Extract essential info
            name = album_details.get('name')
            artist_name = album_details.get('artist') # This should be the corrected artist name
            image_url = None
            if 'image' in album_details:
                # Find the largest image (extralarge or mega)
                for img in album_details['image']:
                    if img['size'] == 'extralarge' and img.get('#text'):
                        image_url = img['#text']
                        break
                    elif img['size'] == 'large' and img.get('#text') and not image_url: # Fallback
                        image_url = img['#text']


            tracks = []
            if 'tracks' in album_details and 'track' in album_details['tracks']:
                track_data_list = album_details['tracks']['track']
                # Ensure it's a list
                if isinstance(track_data_list, dict):
                    track_data_list = [track_data_list]
                for track_item in track_data_list:
                    tracks.append({'name': track_item.get('name')}) # Store as dict for consistency

            return {
                'name': name,
                'artist': artist_name,
                'image_url': image_url,
                'tracks': tracks
            }
        else:
            return None # Album not found or other issue
    except LastfmApiError as e:
        if e.code == 6: # Album not found
            print(f"Album '{album}' by '{artist}' not found on Last.fm.")
        else:
            print(f"Error fetching album details for '{album}': {e}")
        return None


# --- Batch Scrobbling Helper ---
def scrobble_multiple_tracks(tracks_info, session_key, base_timestamp=None, delay_seconds=0.6, progress_callback=None):
    """
    Scrobbles multiple tracks to Last.fm.
    tracks_info: A list of dictionaries, where each dict contains:
                 {'artist': 'Artist Name', 'track': 'Track Name', 'album': 'Album Name' (optional), 'count': N}
    session_key: The authenticated user's session key.
    base_timestamp: The timestamp for the *first* scrobble. Subsequent scrobbles will be
                    incrementally timed to appear as if listened to sequentially.
                    If None, uses the current time.
    delay_seconds: The delay between individual scrobble POST requests.
                   Last.fm API allows up to 50 tracks per batch scrobble.
                   It also has rate limits (e.g., no more than 5 requests per second on average).
    progress_callback: Optional function to report progress (current_count, total_scrobbles, message).
    Returns: A tuple (success_count, failure_count)
    """
    if not session_key:
        raise ValueError("Session key is required to scrobble.")
    if not tracks_info:
        return 0, 0

    total_individual_scrobbles = sum(ti.get('count', 1) for ti in tracks_info)
    scrobbled_count_overall = 0
    successful_scrobbles_overall = 0
    failed_scrobbles_overall = 0

    if base_timestamp is None:
        base_timestamp = int(time.time())

    # We need to generate a list of individual scrobbles with unique timestamps
    all_scrobbles_to_submit = []
    current_ts = base_timestamp

    for track_item in tracks_info:
        artist = track_item['artist']
        track_name = track_item['track']
        album = track_item.get('album') # Optional
        count = track_item.get('count', 1)

        for _ in range(count):
            scrobble_data = {
                'artist': artist,
                'track': track_name,
                'timestamp': current_ts,
            }
            # Only add album parameter if it has a non-empty value
            if album and isinstance(album, str) and album.strip():
                scrobble_data['album'] = album
            all_scrobbles_to_submit.append(scrobble_data)
            # Decrement timestamp for each scrobble to simulate reverse chronological order
            # Average song length is ~3-4 minutes. Let's use 210 seconds (3.5 mins) as a rough guide.
            current_ts -= 210 # This makes them appear as listened to one after another *before* the base_timestamp

    # Last.fm allows batch scrobbling up to 50 tracks at a time.
    MAX_BATCH_SIZE = 50
    num_batches = (len(all_scrobbles_to_submit) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE

    for i in range(num_batches):
        batch = all_scrobbles_to_submit[i * MAX_BATCH_SIZE : (i + 1) * MAX_BATCH_SIZE]
        if not batch:
            continue

        scrobble_params = {}
        for idx, track_data in enumerate(batch):
            scrobble_params[f'artist[{idx}]'] = track_data['artist']
            scrobble_params[f'track[{idx}]'] = track_data['track']
            scrobble_params[f'timestamp[{idx}]'] = track_data['timestamp']
            # Only add album parameter if it exists in track_data
            if 'album' in track_data:
                scrobble_params[f'album[{idx}]'] = track_data['album']

        try:
            # --- Report Progress Before API Call for this Batch ---
            if progress_callback:
                # For message, indicate which batch or overall progress
                progress_msg = f"Batch {i+1}/{num_batches}"
                if len(batch) == 1: # If a small remainder batch
                    progress_msg = f"Track: {batch[0]['track']}"

                # Calculate overall progress based on scrobbles processed so far in *all_scrobbles_to_submit*
                # not just this batch.
                # scrobbled_count_overall is updated *after* API call.
                # So for current progress, it's the start of this batch.
                current_progress_count = i * MAX_BATCH_SIZE
                progress_callback(current_progress_count, total_individual_scrobbles, progress_msg)


            # Make the API call for the current batch
            data = _make_api_request('track.scrobble', http_method='POST', params=scrobble_params, requires_signature=True, requires_session=True, session_key=session_key)

            accepted_in_batch = 0
            ignored_in_batch = 0

            if data and 'scrobbles' in data:
                scrobble_response = data['scrobbles']
                # API returns '@attr' for batch responses, 'scrobble' for single
                if '@attr' in scrobble_response: # Batch response
                    accepted_in_batch = int(scrobble_response['@attr'].get('accepted', 0))
                    ignored_in_batch = int(scrobble_response['@attr'].get('ignored', 0))

                    # Log detailed ignored messages if present
                    if ignored_in_batch > 0 and 'scrobble' in scrobble_response:
                        # 'scrobble' can be a list or a dict if only one was ignored/accepted in a batch
                        ignored_items = scrobble_response['scrobble']
                        if not isinstance(ignored_items, list):
                            ignored_items = [ignored_items]
                        for item in ignored_items:
                            if 'ignoredMessage' in item and item['ignoredMessage'].get('code') != '0': # code 0 is "accepted"
                                track_name = item.get('track', {}).get('corrected', '0')
                                if track_name == '0': track_name = item.get('track', {}).get('#text', 'Unknown Track')

                                artist_name = item.get('artist', {}).get('corrected', '0')
                                if artist_name == '0': artist_name = item.get('artist', {}).get('#text', 'Unknown Artist')

                                ignored_code = item['ignoredMessage'].get('code', 'N/A')
                                ignored_msg = item['ignoredMessage'].get('#text', 'Ignored')
                                print(f"Scrobble ignored ({ignored_code}): {ignored_msg} for {track_name} by {artist_name}")

                elif 'scrobble' in scrobble_response: # Single track was in batch (should be rare with MAX_BATCH_SIZE > 1)
                    single_scrobble_item = scrobble_response['scrobble']
                    if single_scrobble_item['ignoredMessage']['code'] == '0': # Accepted
                        accepted_in_batch = 1
                    else:
                        ignored_in_batch = 1
                        ignored_code = single_scrobble_item['ignoredMessage'].get('code', 'N/A')
                        ignored_msg = single_scrobble_item['ignoredMessage'].get('#text', 'Ignored')
                        track_name = single_scrobble_item.get('track', {}).get('#text', 'Unknown Track')
                        artist_name = single_scrobble_item.get('artist', {}).get('#text', 'Unknown Artist')
                        print(f"Single scrobble in batch ignored ({ignored_code}): {ignored_msg} for {track_name} by {artist_name}")

            successful_scrobbles_overall += accepted_in_batch
            failed_scrobbles_overall += ignored_in_batch # Count Last.fm "ignored" as failures for our summary
            scrobbled_count_overall += len(batch) # All tracks in this batch attempted

            # --- Report Progress After API Call ---
            if progress_callback:
                final_progress_msg = f"Batch {i+1}/{num_batches} done."
                if accepted_in_batch > 0 or ignored_in_batch > 0:
                    final_progress_msg += f" (Accepted: {accepted_in_batch}, Ignored: {ignored_in_batch})"
                progress_callback(scrobbled_count_overall, total_individual_scrobbles, final_progress_msg)

        except LastfmApiError as e:
            print(f"API error during scrobble batch {i+1}: {e}")
            failed_scrobbles_overall += len(batch) # Entire batch failed
            scrobbled_count_overall += len(batch)
            if progress_callback:
                progress_callback(scrobbled_count_overall, total_individual_scrobbles, f"Batch {i+1} API Error")
        except Exception as e:
            print(f"Unexpected error during scrobble batch {i+1}: {e}")
            failed_scrobbles_overall += len(batch)
            scrobbled_count_overall += len(batch)
            if progress_callback:
                progress_callback(scrobbled_count_overall, total_individual_scrobbles, f"Batch {i+1} Unexpected Error")


        # Add delay only if there are more batches to process
        if i < num_batches - 1:
            if progress_callback: # Update message before sleep
                # Use scrobbled_count_overall as it reflects the actual count just processed
                progress_callback(scrobbled_count_overall, total_individual_scrobbles, f"Waiting {delay_seconds}s...")
            time.sleep(delay_seconds)

    # Final progress update if callback is provided
    if progress_callback:
        progress_callback(total_individual_scrobbles, total_individual_scrobbles, "All batches processed.")

    return successful_scrobbles_overall, failed_scrobbles_overall