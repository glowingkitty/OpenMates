# Music app architecture 

## Skills

### Convert to sheet
Takes an audio file as an input and converts it into a music sheet document. For example using klang.io or other providers.

### Search
Searches for tracks, albums, artists, or playlists across multiple providers (e.g., Spotify, Apple Music, YouTube Music). Supports keyword search, filters (genre, mood, popularity), and pagination.

### Manage playlists
Allows creation, modification, and deletion of playlists. Can add, remove, or reorder tracks from user playlists, ensuring a consistent interface across providers.

### Playback control
Controls playback actions such as play, pause, skip, and seek across connected devices and providers. Supports volume adjustment and device switching.

### Get recommendations
Generates song, artist, or playlist recommendations using provider APIs or internal models based on listening history, audio features, or user preferences.

### Get lyrics
Fetches lyrics using providers like Genius, Musixmatch, or similar APIs. Supports retrieving full song lyrics and annotations with metadata.

## Genius API Integration

### Overview
Genius provides a comprehensive API for accessing song lyrics, transcripts, and annotations. The API uses OAuth2 authentication and supports searching for songs, retrieving detailed song information with lyrics, and accessing community annotations.

### Key Endpoints for Transcripts and Lyrics

#### GET /songs/:id
Retrieves detailed song information including lyrics and annotations.

**Parameters:**
- `id` - Song ID
- `text_format` - Optional format for text bodies: `dom`, `plain`, or `html` (defaults to `dom`)

**Response:** Song object containing:
- Title and artist information
- Full lyrics
- Associated referents (annotated sections)
- Annotation data

#### GET /search
Search for songs to find the right track before retrieving full lyrics.

**Parameters:**
- `q` - Search query (required)

**Response:** Array of song matches with IDs for later retrieval

#### GET /referents
Retrieve annotations and comments on specific parts of songs or web pages.

**Parameters:**
- `song_id` - ID of the song
- `created_by_id` - Filter by annotation creator (optional)
- `text_format` - Format for text bodies (optional)
- `per_page` - Results per page (optional)
- `page` - Pagination offset (optional)

### Authentication

1. Register your application at https://genius.com/api-clients to obtain:
   - `client_id`
   - `client_secret`
   - `redirect_uri`

2. Implement OAuth2 authentication flow:
   - Redirect user to `https://api.genius.com/oauth/authorize` with client_id, redirect_uri, scope, and state
   - Exchange authorization code for access token via `https://api.genius.com/oauth/token`
   - Store access token for API requests

3. Include token in API requests:
   ```
   Authorization: Bearer ACCESS_TOKEN
   ```

### Available Scopes

- `me` - Access user account information
- `create_annotation` - Create new annotations
- `manage_annotation` - Update/delete user's annotations
- `vote` - Vote on annotations

### Response Format

All responses are JSON with the following structure:
```json
{
  "meta": {
    "status": 200
  },
  "response": {
    "song": { /* song data */ }
  }
}
```

### Implementation Considerations

- **Rate Limiting**: Implement caching to avoid excessive API calls
- **Text Formatting**: Use `text_format=plain` for simple transcript text, `html` for formatted display
- **Error Handling**: Handle 404 (song not found) and authentication errors gracefully
- **User Sync**: Cache transcript data locally to reduce API dependency
- **Search Workflow**: Search for song first, then retrieve full details by ID

### OAuth2 Libraries
Genius documentation recommends:
- **Python**: rauth, sanction
- **JavaScript**: simple-oauth2, Passport
- **Ruby**: OmniAuth, intridea/oauth2