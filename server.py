from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import re
from aioslsk.settings import Settings, CredentialsSettings
import sys

import asyncio
from aioslsk.client import SoulSeekClient
from aioslsk.commands import PrivateMessageCommand
import threading
import logging

logging.getLogger("aioslsk").setLevel(logging.ERROR)
if sys.platform == 'win32':
    pass
	#asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SS_USERNAME = ''
SS_PASSWORD = ''

config = {}
f = open('config.txt','r',encoding='utf-8')
lines = f.readlines()
f.close()
for line in lines:
    line = line.replace("\n","")
    left = line.split("=")[0]
    right = line.split("=")[1]
    config[left] = right
SS_USERNAME = config['soulseek_username']
SS_PASSWORD = config['soulseek_password']
SAVE_DIR = config['save_directory']
CLICK_THRESHOLD = int(config['click_threshold'])
DAY_THRESHOLD = int(config['day_threshold'])

#f = open('soulseek_creds.txt', 'r', encoding='utf-8')
#lines = f.readlines()
#f.close()
#SS_USERNAME = lines[0].replace("\n", "")
#SS_PASSWORD = lines[1].replace("\n", "")
# Create default settings and configure credentials
settings = Settings(
    credentials=CredentialsSettings(
        username=SS_USERNAME,
        password=SS_PASSWORD
    )
)

settings.network.upnp.enabled = False
settings.network.listening.port = 61000
settings.network.listening.obfuscated_port = 61001
loop = asyncio.new_event_loop()

threading.Thread(
    target=loop.run_forever,
    daemon=True
).start()

#settings.network.upnp.enabled = False

client = SoulSeekClient(settings)
download_lock = asyncio.Lock()
async def soulseek_init():

    print("Starting Soulseek...")
    await client.start()
    print("Started.")

    print("Logging in...")
    await client.login()
    print("Logged in.")
    print("Port:", settings.network.listening.port)
future = asyncio.run_coroutine_threadsafe(
    soulseek_init(),
    loop
)

future.result()
app = Flask(__name__)
CORS(app)

CLICK_DB = "youtube_clicks.db"
MUSIC_DB = "music.db"

ARTIST_INDEX = {}
SONGS_BY_ARTIST = {}

ARTISTS = []

def init_download_db():
    conn = sqlite3.connect("downloads.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            downloaded_at TIMESTAMP NOT NULL,
            UNIQUE(artist, title)
        )
    """)

    conn.commit()
    conn.close()


def init_click_db():
    conn = sqlite3.connect(CLICK_DB)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, clicked_at TIMESTAMP NOT NULL)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_clicks_url_time ON clicks(url, clicked_at)")
    conn.commit()
    conn.close()


def clean_youtube_url(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    video_id = query.get("v")

    if video_id:
        return f"https://www.youtube.com/watch?v={video_id[0]}"

    return url


def record_click(url):
    conn = sqlite3.connect(CLICK_DB, timeout=30)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clicks (url, clicked_at) VALUES (?, ?)", (url, datetime.now()))
    conn.commit()
    conn.close()


def get_recent_click_count(url):
    conn = sqlite3.connect(CLICK_DB, timeout=30)
    cursor = conn.cursor()
    cutoff = datetime.now() - timedelta(days=DAY_THRESHOLD)
    cursor.execute("SELECT COUNT(*) FROM clicks WHERE url = ? AND clicked_at > ?", (url, cutoff))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def normalise_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_artist_area(title):
    title = title.replace(" - YouTube", "")

    for sep in [" - ", " | ", " : ", " – ", ":"]:
        if sep in title:
            return title.split(sep)[0]

    return title
def find_best_match(title, description):
    import re
    import sqlite3
    from difflib import SequenceMatcher

    def clean(s):
        if not s:
            return ""

        s = re.split(r"[\(\[]", s, 1)[0]

        s = re.sub(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", "", s, flags=re.I)

        s = re.split(r"\s+-\s+", s, 1)[0]

        s = normalise_text(s)
        s = re.sub(r"\s+", " ", s)

        return s.strip()

    def is_valid_guess(s, min_len=2):
        """Reject empty strings, pure-symbol strings (e.g. '?????????'
        from botched unicode normalisation), and guesses that are too
        short to be meaningful (e.g. 'Go!')."""
        if not s:
            return False
        if len(s) < min_len:
            return False
        # must contain at least 2 alphanumeric characters (unicode-aware)
        if len(re.findall(r"\w", s, flags=re.UNICODE)) < 2:
            return False
        return True

    def similarity(a, b):
        return SequenceMatcher(None, a, b).ratio()

    print("starting db check")

    title = title.replace(" - YouTube", "").strip()

    conn = sqlite3.connect(MUSIC_DB, timeout=30)
    cursor = conn.cursor()

    def score_against_artist(real_artist, song_guess):
        """Given a resolved DB artist and a candidate song title, fetch
        that artist's songs and return (best_score, best_dict) or
        (0, None) if nothing usable."""

        if not is_valid_guess(song_guess):
            return 0, None

        cursor.execute(
            "SELECT artist,title FROM songs WHERE lower(artist)=lower(?)",
            (real_artist,)
        )
        rows = cursor.fetchall()

        best_local = None
        best_local_score = 0

        for db_artist, db_song in rows:

            if clean(db_artist) == song_guess:
                continue

            song_clean = clean(db_song)

            score = 1.0 if song_clean == song_guess else similarity(song_clean, song_guess)

            if score > best_local_score:
                best_local_score = score
                best_local = {"artist": db_artist, "song": db_song}

        return best_local_score, best_local

    def try_artist_guess(artist_guess, song_guess):
        """Resolve artist_guess through ARTIST_INDEX and score it
        against song_guess. Returns (score, result_dict, real_artist)
        or (0, None, None) if the artist isn't recognised."""

        artist_guess = clean(artist_guess) if artist_guess else ""

        if not is_valid_guess(artist_guess):
            return 0, None, None

        real_artist = ARTIST_INDEX.get(artist_guess)

        if not real_artist:
            return 0, None, None

        score, result = score_against_artist(real_artist, clean(song_guess))
        return score, result, real_artist

    # A song-similarity score this high is treated as "good enough" -
    # not worth burning more DB/regex work chasing a marginally
    # better interpretation.
    EARLY_EXIT_SCORE = 0.95

    # Overall best across every interpretation we try below
    overall_best = None
    overall_best_score = 0
    overall_best_artist = None  # real_artist string, used as fallback
                                 # when we found the artist but not a
                                 # confident song match
    artist_resolved = False     # True once ANY stage successfully
                                 # resolved a real artist via
                                 # ARTIST_INDEX - gates the expensive
                                 # last-resort full-index scan below

    def consider(score, result, real_artist):
        nonlocal overall_best, overall_best_score, overall_best_artist, artist_resolved
        if real_artist:
            artist_resolved = True
            if overall_best_artist is None:
                overall_best_artist = real_artist
        if score > overall_best_score:
            overall_best_score = score
            overall_best = result
            if real_artist:
                overall_best_artist = real_artist

    # -----------------------------------------------------
    # Fast path: YouTube's auto-generated Content ID
    # description format for label uploads looks like:
    #
    #   Provided to YouTube by Universal Music Group
    #   The Logical Song · Supertramp
    #   Breakfast in America
    #   ...
    #
    # The "Song · Artist" line is extremely reliable when
    # present, and MUCH cheaper than the last-resort scan.
    # Tried first since it's common and precise - avoids the
    # "by Artist" stage misfiring on "by Universal Music
    # Group" style label credits, and avoids the full
    # ARTIST_INDEX scan entirely when it hits.
    # -----------------------------------------------------

    if overall_best_score < EARLY_EXIT_SCORE:

        dot_match = re.search(r"([^\n·]+?)\s*·\s*([^\n·]+)", description)

        if dot_match:
            song_part = clean(dot_match.group(1))
            artist_part = clean(dot_match.group(2))

            score_e, result_e, artist_e = try_artist_guess(artist_part, song_part)
            consider(score_e, result_e, artist_e)

    # -----------------------------------------------------
    # Title has a separator: try "Artist - Song" first (the
    # common case). Only try the reversed "Song - Artist"
    # ordering if the first interpretation wasn't already a
    # confident match - most titles are the common order, so
    # this avoids a second DB round-trip on the easy cases.
    # -----------------------------------------------------

    part1, part2 = None, None

    for sep in [" - ", " – ", " | ", ": "]:
        if sep in title:
            part1, part2 = title.split(sep, 1)
            break

    if part1 is not None:

        print("TITLE PART1:", clean(part1))
        print("TITLE PART2:", clean(part2))

        # Interpretation A: Artist - Song (the common case)
        score_a, result_a, artist_a = try_artist_guess(part1, part2)
        consider(score_a, result_a, artist_a)

        # Interpretation B: Song - Artist (reversed) - skip if A
        # already gave us a confident match
        if overall_best_score < EARLY_EXIT_SCORE:
            score_b, result_b, artist_b = try_artist_guess(part2, part1)
            consider(score_b, result_b, artist_b)

    # -----------------------------------------------------
    # No confident match yet - look for the artist in the
    # description instead, using the fullest reasonable
    # song guess we have (whichever title part wasn't
    # consumed as the artist, or the whole title if there
    # was no separator at all).
    # -----------------------------------------------------

    if overall_best_score < EARLY_EXIT_SCORE:

        fallback_song_guess = clean(title) if part1 is None else clean(part2)

        desc = clean(description)

        # "by Artist" phrasing in the description
        match = re.search(r"\bby\s+([a-z0-9 '&.]+)", desc, flags=re.I)

        if match:
            possible_artist = clean(match.group(1))
            score_c, result_c, artist_c = try_artist_guess(possible_artist, fallback_song_guess)
            consider(score_c, result_c, artist_c)

        # Last resort - scan known artists against the description.
        # This is O(number of artists) regex matches, so it's gated
        # behind artist_resolved: if we already found a real artist
        # via the title or the "by Artist" phrase, there's no reason
        # to pay for the full scan even if the song-title score was
        # mediocre - we trust the resolved artist and accept a
        # lower-confidence song match (returned as song=None below)
        # rather than re-searching from scratch.
        #
        # Fixed: plain substring matching let short/generic artist
        # names (e.g. "Go!") false-positive against almost any
        # description. Now requires a word-boundary match, a minimum
        # artist-name length, and only keeps the single longest
        # (most specific) matching artist name.
        if overall_best_score < EARLY_EXIT_SCORE and not artist_resolved:

            desc_lower = desc.lower()
            best_artist_match = None  # (real_artist, matched_len)

            for artist_clean, real_artist in ARTIST_INDEX.items():

                if not is_valid_guess(artist_clean, min_len=3):
                    continue

                pattern = r"\b" + re.escape(artist_clean.lower()) + r"\b"

                if re.search(pattern, desc_lower):
                    if best_artist_match is None or len(artist_clean) > best_artist_match[1]:
                        best_artist_match = (real_artist, len(artist_clean))

            if best_artist_match:
                real_artist = best_artist_match[0]
                score_d, result_d = score_against_artist(real_artist, fallback_song_guess)
                consider(score_d, result_d, real_artist)

    conn.close()

    print("BEST SCORE:", overall_best_score)

    if overall_best_score < 0.75:
        if overall_best_artist:
            return {
                "artist": overall_best_artist,
                "song": None
            }
        return None

    print("Matched:", overall_best)

    return overall_best
import os
import re
from difflib import SequenceMatcher

def clean_filename(text):
    text = os.path.basename(text)
    text = text.lower()

    text = re.sub(r"\.(mp3|flac|m4a|ogg|wav)$", "", text)
    text = re.sub(r"[_\.]", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()

async def download_song(artist, title):
    async with download_lock:
        if already_downloaded(artist, title):
            print("Already downloaded:", artist, "-", title)
            return None
        import os
        import traceback
        from difflib import SequenceMatcher

        print("Searching...")

        request = await client.searches.search(f"{artist} {title} mp3")
        await asyncio.sleep(5)

        wanted = clean_filename(f"{artist} - {title}")
        candidates = []
        print("results:", len(request.results))
        for result in request.results:
            for file in result.shared_items:
                if not file.filename.lower().endswith(".mp3"):
                    continue
                if file.filesize > 15 * 1024 * 1024:
                    continue
                filename = clean_filename(file.filename)
                score = SequenceMatcher(None, filename, wanted).ratio()

                # prefer larger files slightly (existing behaviour)
                score += min(file.filesize / 15000000, 0.20)

                # prefer users with faster upload speeds
                score += min(result.avg_speed / 5000000, 0.30)

                # prefer users with free slots
                if result.has_free_slots:
                    score += 0.10

                # avoid huge queues
                if result.queue_size:
                    score -= min(result.queue_size / 100, 0.20)

                candidates.append({
                    "username": result.username,
                    "filename": file.filename,
                    "score": score,
                    "filesize": file.filesize,
                    "speed": result.avg_speed,
                    "queue": result.queue_size
                })
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        print("candidates:", len(candidates))
        for candidate in candidates[:5]:

            print()
            print("Trying:", candidate["username"])
            print(candidate["filename"])
            print("Score:", round(candidate["score"], 3))
            if title.lower() not in candidate["filename"].lower(): continue
            transfer = None

            try:
                try:
                    transfer = await client.transfers.download(
                        candidate["username"],
                        candidate["filename"]
                    )

                except Exception as e:
                    print("Could not start transfer:", e)
                    continue

                print("Initial:", type(transfer.state).__name__)

                last_state = None

                for _ in range(10):

                    state = type(transfer.state).__name__

                    if state != last_state:
                        print(
                            "State:",
                            state,
                            "queue:",
                            transfer.place_in_queue,
                            "remote:",
                            transfer.remotely_queued,
                            "bytes:",
                            transfer.bytes_transfered,
                            "fail:",
                            transfer.fail_reason
                        )
                        last_state = state

                    if transfer.is_transferring() or transfer.bytes_transfered > 0:
                        print("Transfer started!")
                        break

                    if transfer.is_finalized() or transfer.fail_reason:
                        print("Failed:", transfer.fail_reason)
                        break

                    await asyncio.sleep(1)

                else:
                    print("Peer never accepted transfer")
                    try:
                        await client.transfers.abort(transfer)
                    except:
                        pass
                    continue

                last_bytes = -1
                idle = 0

                while not transfer.is_transfered():

                    if transfer.is_finalized():
                        print("Transfer failed:", transfer.fail_reason)
                        break

                    current = transfer.bytes_transfered

                    print("Downloading:", current, "/", transfer.filesize)

                    if current == last_bytes:
                        idle += 1
                    else:
                        idle = 0

                    last_bytes = current

                    if idle > 120:
                        print("Transfer stalled")
                        break

                    await asyncio.sleep(1)

                if transfer.is_transfered():

                    print("Download complete")

                    src = transfer.local_path

                    dest_dir = os.path.join(SAVE_DIR, artist)
                    os.makedirs(dest_dir, exist_ok=True)

                    dest = os.path.join(dest_dir, f"{artist} - {title}.mp3")

                    os.replace(src, dest)

                    print("Saved:", dest)
                    try:
                        await client.transfers.abort(transfer)
                    except:
                        pass

                    record_download(artist, title)
                    try:
                        await client.searches.cancel(request.ticket)
                    except Exception:
                        pass
                    return dest

            except Exception:
                traceback.print_exc()

                if transfer:
                    try:
                        await client.transfers.abort(transfer)
                        await asyncio.sleep(1)
                    except Exception as e:
                        print("Abort failed:", e)

        print("Couldn't download from any candidate.")
        return None
@app.route("/youtube", methods=["POST"])
def youtube():
    print("POST RECEIVED")
    print("=" * 60)
    print("REQUEST RECEIVED")

    data = request.get_json()

    url = clean_youtube_url(data.get("url"))

    print("URL:", url)
    print("Title:", data.get("title"))
    print("Description:", data.get("description"))

    record_click(url)

    clicks = get_recent_click_count(url)

    print("Clicks last 3 days:", clicks)
    if clicks < CLICK_THRESHOLD: return {}
    match = find_best_match(data.get("title", ""), data.get("description", ""))

    print("MATCH:", match)
    
    match_artist = match['artist']
    match_song = match['song']
    if match_song is not None: match_song = match_song.split("(")[0].split("[")[0]
    if match and match_artist and match_song:
        future = asyncio.run_coroutine_threadsafe(
            download_song(match_artist, match_song),
            loop
        )

        future.result()    # optional, waits for it to finish

    print("=" * 60)

    return jsonify({
        "status": "ok",
        "url": url,
        "clicks": clicks,
        "match": match,
        "download": clicks > 3
    })

def already_downloaded(artist, title):
    conn = sqlite3.connect("downloads.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM downloads WHERE artist=? AND title=?",
        (artist, title)
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None

def record_download(artist, title):
    conn = sqlite3.connect("downloads.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO downloads
        (artist, title, downloaded_at)
        VALUES (?, ?, ?)
        """,
        (artist, title, datetime.now())
    )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_click_db()
    init_download_db()
    conn = sqlite3.connect(MUSIC_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT artist FROM songs")

    for (artist,) in cursor.fetchall():
        ARTIST_INDEX[normalise_text(artist)] = artist

    conn.close()

    print("Loaded", len(ARTIST_INDEX), "artists")

    app.run(host="0.0.0.0", port=5001)
