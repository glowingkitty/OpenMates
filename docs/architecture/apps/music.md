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

### Lyrics and annotations
Fetches or synchronizes lyrics and song annotations using APIs like Musixmatch or Genius.