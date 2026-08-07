import json
import sqlite3

# Connect to SQLite
conn = sqlite3.connect("music.db")
cursor = conn.cursor()

# Create table
cursor.execute("""
CREATE TABLE IF NOT EXISTS songs (
    recording_id TEXT PRIMARY KEY,
    artist TEXT,
    title TEXT,
    album TEXT
)
""")

count = 0

with open("release", encoding="utf-8") as f:
    for line in f:

        try:
            release = json.loads(line)
        except Exception:
            continue

        album = release.get("title", "")

        for media in release.get("media", []):
            for track in media.get("tracks", []):

                recording = track.get("recording", {})

                recording_id = recording.get("id")

                title = recording.get("title") or track.get("title")

                if not recording_id or not title:
                    continue

                for credit in track.get("artist-credit", []):

                    artist = credit.get("name")

                    if not artist:
                        continue

                    try:
                        cursor.execute("""
                            INSERT INTO songs
                            (recording_id, artist, title, album)
                            VALUES (?, ?, ?, ?)
                        """, (
                            recording_id,
                            artist,
                            title,
                            album
                        ))

                        count += 1

                    except sqlite3.IntegrityError:
                        # Recording already exists
                        pass

        # Commit every 1000 inserts
        if count % 1000 == 0:
            conn.commit()
            print(f"{count:,} songs imported...")

conn.commit()
conn.close()

print(f"\nFinished! Imported {count:,} songs.")