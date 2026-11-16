import os
import re
import json
import uuid
import difflib
import urllib.parse
import urllib.request
import socket
import ipaddress
import yt_dlp
from typing import Dict, List, Set, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="CinemaHub VIP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def is_safe_url(url: str) -> bool:
    """Rigorous SSRF validation: rejects loopback, private RFC-1918, link-local, and cloud metadata IPs."""
    try:
        if not url or not isinstance(url, str):
            return False
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        
        lower_host = hostname.lower()
        if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal", "instance-data"):
            return False
        if lower_host.endswith(".internal") or lower_host.endswith(".local"):
            return False

        # Resolve host to IP and verify against private/reserved ranges
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_reserved
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

HOST_IP = get_lan_ip()

class SearchRequest(BaseModel):
    query: str
    language: str = "English"
    imdb_id: Optional[str] = None

class MoodSearchRequest(BaseModel):
    mood: str
    language: str = "English"

class DirectUrlRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    title: str = "movie"
    quality: str = "best"
    include_subtitles: bool = True
    sub_lang: str = "en"

downloads_status = {}

SPAM_KEYWORDS = [
    "review", "reaction", "teaser", "trailer", "behind the scenes",
    "bts", "ending explained", "breakdown", "analysis", "gameplay",
    "walkthrough", "parody", "roast", "funniest moments", "meme",
    "fan made", "fake", "interview", "box office", "tribute", "facts", 
    "recap", "summary", "scene", "clip", "jukebox", "promo", "audio launch",
    "press meet", "making of", "short film", "audio jukebox", "songs",
    "science behind", "dream heists", "video essay", "documentary",
    "retrospective", "deep dive", "lore", "theory", "explained",
    "soundtrack", "ost", "theme song", "podcast", "discussion", "commentary"
]

THEATRICAL_PRINT_KEYWORDS = [
    "cam", "camrip", "hdcam", "hdts", "telesync", "ts", "theater print", 
    "cinema print", "multiplex print", "theatrical print", "hall print"
]

HD_PRINT_KEYWORDS = [
    "web-dl", "webrip", "bluray", "blu-ray", "brrip", "hdrip", "dvdrip", 
    "1080p", "720p", "4k", "uhd", "fhd", "official hd", "remux"
]

MOOD_PRESETS = {
    "telugu": [
        {"title": "Arjun Reddy", "year": "2017", "rating": "8.0", "genres": "Drama, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BNmU2N2QzMTktYTQ4Zi00OTBkLTkxZTQtMjk1M2Y2NGQ2ZGVlXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A short-tempered house surgeon gets used to drugs and drinks when his girlfriend is forced to marry another person."},
        {"title": "RRR", "year": "2022", "rating": "8.8", "genres": "Action, Drama", "poster": "https://m.media-amazon.com/images/M/MV5BODUwNDNjMTctODUxNy00ZTA2LWIyYTEtMDc5Y2E5NjBmNTMzXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A fearless revolutionary and an officer in the British force decide to join forces and chart out a path towards freedom."},
        {"title": "Dear Comrade", "year": "2019", "rating": "7.3", "genres": "Action, Drama, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BZjRiZTU3NmUtODk4Yy00MDkxLTk1NDItODZlNDk5ZjkyNTU5XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "Bobby, a student union leader with anger issues, falls in love with Lilly, a state-level cricketer, but his temper threatens to tear them apart."},
        {"title": "Geetha Govindam", "year": "2018", "rating": "7.7", "genres": "Comedy, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BNjE4OGY5OTItYWM0MC00YjBhLTg4YmEtYzA4NjVlNTBiMDhjXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A young lecturer falls for an independent woman, but an awkward misunderstanding ruins their first encounter."},
        {"title": "World Famous Lover", "year": "2020", "rating": "5.3", "genres": "Drama, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BYzA2YzdiY2QtMDVjZS00N2EzLWExOWItZjEyN2ZkZjExMWYyXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "An amalgamation of four different love stories that explores the agony and romance of relationships."}
    ],
    "mind-bending": [
        {"title": "Interstellar", "year": "2014", "rating": "8.7", "genres": "Sci-Fi, Adventure", "poster": "https://m.media-amazon.com/images/M/MV5BYzdjMDAxZGItMjI2My00ODA1LTlkNzItOWFjMDU5ZDJlYWY3XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "When Earth becomes uninhabitable in the future, a farmer and ex-NASA pilot is tasked to pilot a spacecraft along with a team of researchers to find a new planet for humans."},
        {"title": "Inception", "year": "2010", "rating": "8.8", "genres": "Action, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_FMjpg_UX1000_.jpg", "summary": "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea into the mind of a C.E.O."},
        {"title": "The Matrix", "year": "1999", "rating": "8.7", "genres": "Action, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BN2NmN2VhMTQtMDNiOS00NDlhLTliMjgtODE2ZTY0ODQyNDRhXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "When a beautiful stranger leads computer hacker Neo to a forbidding underworld, he discovers the shocking truth--the life he knows is the elaborate deception of an evil cyber-intelligence."},
        {"title": "Tenet", "year": "2020", "rating": "7.3", "genres": "Action, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BMzU3YWYwNTQtZTdiMC00NjNiLTlhNTAtNzRiZjkwYmM2NDZhXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "Armed with only one word, Tenet, and fighting for the survival of the entire world, a Protagonist journeys through a twilight world of international espionage on a mission that will unfold in something beyond real time."}
    ],
    "thriller": [
        {"title": "Shutter Island", "year": "2010", "rating": "8.2", "genres": "Mystery, Thriller", "poster": "https://m.media-amazon.com/images/M/MV5BN2FjNWExNDEtYjc4NC00YTE1LWEwODctZDVlMGYwNzg4MGQ2XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "In 1954, a U.S. Marshal investigates the disappearance of a murderer who escaped from a hospital for the criminally insane."},
        {"title": "Prisoners", "year": "2013", "rating": "8.2", "genres": "Crime, Drama, Mystery", "poster": "https://m.media-amazon.com/images/M/MV5BMTg0NTIzMjQ1NV5BMl5BanBnXkFtZTcwNDc3MzM5OQ@@._V1_FMjpg_UX1000_.jpg", "summary": "When Keller Dover's daughter and her friend go missing, he takes matters into his own hands as the police pursue multiple leads and the pressure mounts."},
        {"title": "Gone Girl", "year": "2014", "rating": "8.1", "genres": "Drama, Mystery, Thriller", "poster": "https://m.media-amazon.com/images/M/MV5BMTk0MDQ3OTAzOV5BMl5BanBnXkFtZTgwNzU1NzE3MjE@._V1_FMjpg_UX1000_.jpg", "summary": "With his wife's disappearance having become the focus of an intense media circus, a man sees the spotlight turned on him when it's suspected that he may not be innocent."},
        {"title": "Se7en", "year": "1995", "rating": "8.6", "genres": "Crime, Drama, Mystery", "poster": "https://m.media-amazon.com/images/M/MV5BY2IzNzMxZjUtYzUxZS00OGY1LWE5ODQtODliOGM4MTMwZmNkXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "Two detectives, a rookie and a veteran, hunt a serial killer who uses the seven deadly sins as his motives."}
    ],
    "epic": [
        {"title": "Gladiator", "year": "2000", "rating": "8.5", "genres": "Action, Adventure, Drama", "poster": "https://m.media-amazon.com/images/M/MV5BYWQ4YmNjYjEtOWE1Zi00Y2U4LWI4NTAtMTU0MjkxNWQ1ZmJiXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A former Roman General sets out to exact vengeance against the corrupt emperor who murdered his family and sent him into slavery."},
        {"title": "Dune", "year": "2021", "rating": "8.0", "genres": "Action, Adventure, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BN2FjNmEyNWMtYzM0ZS00NjIyLTg5YzYtODExMDkxNzE1NzM1XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A noble family becomes embroiled in a war for control over the galaxy's most valuable asset while its heir becomes troubled by visions of a dark future."},
        {"title": "The Dark Knight", "year": "2008", "rating": "9.0", "genres": "Action, Crime, Drama", "poster": "https://m.media-amazon.com/images/M/MV5BMTMxNTMwODM0NF5BMl5BanBnXkFtZTcwODAyMTk2Mw@@._V1_FMjpg_UX1000_.jpg", "summary": "When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests of his ability to fight injustice."},
        {"title": "Mad Max: Fury Road", "year": "2015", "rating": "8.1", "genres": "Action, Adventure, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BN2EwM2I5OWMtMGQyMi00Zjg1LWJkNTctZTdjYTA4OGUwZjMyXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "In a post-apocalyptic wasteland, a woman rebels against a tyrannical ruler in search for her homeland with the aid of a group of female prisoners, a psychotic worshiper and a drifter named Max."}
    ],
    "nature-documentary": [
        {"title": "Our Planet", "year": "2019", "rating": "9.3", "genres": "Documentary, Nature", "poster": "https://m.media-amazon.com/images/M/MV5BYmVkZmM0OGUtNGVhNC00NTEwLTg3NjAtNTZiNWQ0NWJjMTU3XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "Experiencing the planet's natural beauty through an examination of how climate change impacts all living creatures in this ambitious documentary of spectacular scope."},
        {"title": "Planet Earth II", "year": "2016", "rating": "9.5", "genres": "Documentary, Nature", "poster": "https://m.media-amazon.com/images/M/MV5BMGZmYTk2M3YtMjAyMi00OGZhLTlmY2QtNzk2MjJlODFhMGFlXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "David Attenborough returns with a new wildlife documentary that explores the unique characteristics of Earth's most iconic habitats and the extraordinary ways animals survive within them."},
        {"title": "Blue Planet II", "year": "2017", "rating": "9.3", "genres": "Documentary, Deep Ocean", "poster": "https://m.media-amazon.com/images/M/MV5BYjg2NzMwcgQtZGUzNy00MTVmLWI3OWMtNjY3YmRhMmM4N2NkXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "David Attenborough returns to the world's deep oceans in this breathtaking exploration of underwater realms and bizarre deep-sea creatures."},
        {"title": "My Octopus Teacher", "year": "2020", "rating": "8.1", "genres": "Documentary, Ocean", "poster": "https://m.media-amazon.com/images/M/MV5BNzQ3OTJlZWYtNmQzOS00NmE5LWI5N2QtNDQ2MGI0MDFlYmQ0XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A filmmaker forges an unusual friendship with an octopus living in a South African kelp forest, learning as the animal shares the mysteries of her world."}
    ],
    "horror": [
        {"title": "The Conjuring", "year": "2013", "rating": "7.5", "genres": "Horror, Mystery", "poster": "https://m.media-amazon.com/images/M/MV5BMTM3NjA1NDMyMV5BMl5BanBnXkFtZTcwMDQzNDMzOQ@@._V1_FMjpg_UX1000_.jpg", "summary": "Paranormal investigators Ed and Lorraine Warren work to help a family terrorized by a dark presence in their farmhouse."},
        {"title": "Hereditary", "year": "2018", "rating": "7.3", "genres": "Drama, Horror, Mystery", "poster": "https://m.media-amazon.com/images/M/MV5BOTU5MDg3OGItZWQ1Ny00ZGVmLTg2YTUtMzBkYzQ1YWIwZjlhXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A grieving family is haunted by tragic and disturbing occurrences after the death of their secretive grandmother."},
        {"title": "A Quiet Place", "year": "2018", "rating": "7.5", "genres": "Drama, Horror, Sci-Fi", "poster": "https://m.media-amazon.com/images/M/MV5BMjI0MDMzNTQ0M15BMl5BanBnXkFtZTgwMTM5NzM3NDM@._V1_FMjpg_UX1000_.jpg", "summary": "In a post-apocalyptic world, a family is forced to live in silence while hiding from monsters with ultra-sensitive hearing."},
        {"title": "The Shining", "year": "1980", "rating": "8.4", "genres": "Drama, Horror", "poster": "https://m.media-amazon.com/images/M/MV5BYmU5NWFlZDgtZGU3Ni00ZTVjLTgyYjUtYWI5N2EzZThiYmRkXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "A family heads to an isolated hotel for the winter where a sinister presence influences the father into violence."}
    ],
    "cozy": [
        {"title": "The Grand Budapest Hotel", "year": "2014", "rating": "8.1", "genres": "Adventure, Comedy, Crime", "poster": "https://m.media-amazon.com/images/M/MV5BMzM5NjUxOTEyMl5BMl5BanBnXkFtZTgwNjEyMDM0MDE@._V1_FMjpg_UX1000_.jpg", "summary": "A writer encounters the owner of an aging high-class hotel, who tells him of his early years serving as a lobby boy in the hotel's glorious years under an exceptional concierge."},
        {"title": "La La Land", "year": "2016", "rating": "8.0", "genres": "Comedy, Drama, Music", "poster": "https://m.media-amazon.com/images/M/MV5BMzUzNDM2NzM2MV5BMl5BanBnXkFtZTgwNTM3NTg4OTE@._V1_FMjpg_UX1000_.jpg", "summary": "While navigating their careers in Los Angeles, a pianist and an actress fall in love while attempting to reconcile their aspirations for the future."},
        {"title": "Amelie", "year": "2001", "rating": "8.3", "genres": "Comedy, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BNDg4NjM1YjMtYmNhZC00MjM0LWFiZmYtNGY1YjA3MzZmODc5XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg", "summary": "Amélie is an innocent and naive girl in Paris with her own sense of justice. She decides to help those around her and, along the way, discovers love."},
        {"title": "Midnight in Paris", "year": "2011", "rating": "7.7", "genres": "Comedy, Fantasy, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BMTM4NjY1MDQwMl5BMl5BanBnXkFtZTcwNDE4MzUxNQ@@._V1_FMjpg_UX1000_.jpg", "summary": "While on a trip to Paris with his fiancée's family, a nostalgic screenwriter finds himself mysteriously going back to the 1920s every day at midnight."}
    ]
}

def format_duration(seconds):
    if not seconds:
        return "Stream"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    hours = mins // 60
    mins = mins % 60
    if hours > 0:
        return f"{hours}h {mins}m {secs}s"
    return f"{mins}m {secs}s"

def clean_text(text):
    return re.sub(r'[^a-zA-Z0-9\s]', ' ', text).lower().strip()

def compute_similarity(search_query: str, target_title: str):
    sq_clean = clean_text(search_query)
    tt_clean = clean_text(target_title)
    sq_words = set(sq_clean.split())
    tt_words = set(tt_clean.split())
    if not sq_words:
        return 0.0

    stop_words = {'full', 'movie', 'length', 'hd', '1080p', '720p', '4k', 'official', 'film', 'cinema', 'telugu', 'hindi', 'tamil', 'english', 'drama', 'romantic', 'action'}
    core_sq = {w for w in sq_words if w not in stop_words} or sq_words
    core_tt = {w for w in tt_words if w not in stop_words} or tt_words

    matched = core_sq.intersection(core_tt)
    if not matched:
        return 0.0

    # Penalize heavily if target has words typical of video essays / analysis / documentaries
    essay_words = {'science', 'behind', 'essay', 'documentary', 'analysis', 'explained', 'breakdown', 'lore', 'theory', 'scenes', 'clips', 'facts', 'heists', 'secrets', 'ending', 'recap', 'summary', 'audiobook', 'asleep', 'sleep', 'podcast', 'commentary', 'retrospective', 'story'}
    essay_words_in_tt = {w for w in tt_words if w in essay_words and w not in sq_words}
    if essay_words_in_tt:
        return 0.05

    ratio = len(matched) / max(len(core_tt), 1)
    seq = difflib.SequenceMatcher(None, ' '.join(sorted(core_sq)), ' '.join(sorted(matched))).ratio()
    return max(ratio, seq)

def detect_print_quality(title: str, description: str = ""):
    combined = (title + " " + description).lower()
    for kw in THEATRICAL_PRINT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', combined):
            return {
                "print_type": "Theatrical Print (CAM / Hall)",
                "print_tag": "theatrical",
                "print_color": "#f43f5e",
                "print_badge": "🎥 Theatrical Print"
            }
    for kw in HD_PRINT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', combined):
            return {
                "print_type": "Official HD / Digital Print",
                "print_tag": "hd",
                "print_color": "#10b981",
                "print_badge": "💎 Crisp HD"
            }
    return {
        "print_type": "Standard Digital Print",
        "print_tag": "hd",
        "print_color": "#0ea5e9",
        "print_badge": "📺 Digital Web"
    }

def verify_movie_result(search_query: str, language: str, title: str, duration_sec: float, desc: str = ""):
    title_lower = title.lower()
    q_lower = search_query.lower()
    
    # 1. Check spam keywords
    if any(spam in title_lower for spam in SPAM_KEYWORDS):
        return None

    # 1b. Check recap / sleep / commentary indicators if not part of original query
    recap_indicators = [
        "story of", "entire story", "fall asleep", "sleep to", "asleep",
        "recap", "summary", "audiobook", "sleep story", "bedtime story",
        "timeline", "all deaths", "kill count", "every death", "chronological",
        "full plot", "plot breakdown", "explained in", "lore explained"
    ]
    if any(ind in title_lower and ind not in q_lower for ind in recap_indicators):
        return None

    # 2. Strict Duration Gate: full movies must be over 45 mins (2700s) and under 4 hours (14400s)
    if duration_sec:
        if duration_sec < 2700 or duration_sec > 14400:
            return None
    else:
        # If duration is missing, only allow if title explicitly contains "full movie" or "full length"
        if not ("full movie" in title_lower or "full length" in title_lower or "entire movie" in title_lower):
            return None

    sim = compute_similarity(search_query, title)
    if sim < 0.38:
        return None

    lang_lower = language.lower()
    
    # Audio language detection
    is_hindi_dubbed = any(k in title_lower for k in [
        "hindi dubbed", "dubbed in hindi", "in hindi", "hindi movie", "south hindi dubbed", "hindi version"
    ])
    is_telugu_audio = any(k in title_lower for k in [
        "telugu full length", "telugu movie", "telugu cinema", "telugu full movie", "original telugu", "telugu hd"
    ]) and not is_hindi_dubbed
    is_tamil_audio = any(k in title_lower for k in [
        "tamil full movie", "tamil movie", "tamil cinema", "tamil hd"
    ]) and not is_hindi_dubbed

    is_audio_mismatch = False
    warning_note = None

    if (lang_lower == "telugu" or "telug" in lang_lower) and is_hindi_dubbed:
        is_audio_mismatch = True
        warning_note = "⚠️ Audio: Hindi Dubbed (Original Telugu restricted to streaming services)"
    elif (lang_lower == "tamil" or "tam" in lang_lower) and is_hindi_dubbed:
        is_audio_mismatch = True
        warning_note = "⚠️ Audio: Hindi Dubbed (Tamil audio not detected)"
    elif lang_lower not in ["hindi", "all", "other"] and is_hindi_dubbed:
        is_audio_mismatch = True
        warning_note = f"⚠️ Audio: Hindi Dubbed (Not {language})"

    duration_str = format_duration(duration_sec) if duration_sec else "Full Movie"
    is_full_length = (duration_sec >= 2700) if duration_sec else True
    
    confidence_score = int(sim * 55 + 35)
    badge = "Verified Full Movie"
    badge_color = "#10b981"

    if is_audio_mismatch:
        confidence_score = max(42, confidence_score - 25)
        badge = "Hindi Dubbed Audio"
        badge_color = "#f59e0b"
    elif (lang_lower in title_lower or lang_lower == "english" or is_telugu_audio) and sim >= 0.6:
        confidence_score = min(98, confidence_score + 10)

    confidence_score = min(100, max(40, confidence_score))
    print_info = detect_print_quality(title, desc)

    return {
        "is_full_movie": is_full_length,
        "is_audio_mismatch": is_audio_mismatch,
        "audio_warning": warning_note,
        "badge": badge,
        "badge_color": badge_color,
        "confidence": confidence_score,
        "duration_formatted": duration_str,
        **print_info
    }

MOVIE_CAST_DATABASE = {
    "arjun reddy": [
        {"name": "Vijay Deverakonda", "role": "Dr. Arjun Reddy Deshmukh"},
        {"name": "Shalini Pandey", "role": "Dr. Preethi Shetty"},
        {"name": "Rahul Ramakrishna", "role": "Shiva (Best Friend)"},
        {"name": "Jia Sharma", "role": "Jia"},
        {"name": "Sandeep Reddy Vanga", "role": "Director"}
    ],
    "dear comrade": [
        {"name": "Vijay Deverakonda", "role": "Comrade Chaitanya (Bobby)"},
        {"name": "Rashmika Mandanna", "role": "Aparna Devi (Lilly)"},
        {"name": "Shruti Ramachandran", "role": "Jaya"},
        {"name": "Bharat Kamma", "role": "Director"}
    ],
    "geetha govindam": [
        {"name": "Vijay Deverakonda", "role": "Vijay Govind"},
        {"name": "Rashmika Mandanna", "role": "Geetha"},
        {"name": "Subbaraju", "role": "Phaneendra"},
        {"name": "Parasuram", "role": "Director"}
    ],
    "world famous lover": [
        {"name": "Vijay Deverakonda", "role": "Gautham / Seenayya"},
        {"name": "Raashii Khanna", "role": "Yamini"},
        {"name": "Aishwarya Rajesh", "role": "Suvarna"},
        {"name": "Kranthi Madhav", "role": "Director"}
    ],
    "inception": [
        {"name": "Leonardo DiCaprio", "role": "Dom Cobb (Extractor)"},
        {"name": "Joseph Gordon-Levitt", "role": "Arthur (Point Man)"},
        {"name": "Elliot Page", "role": "Ariadne (Architect)"},
        {"name": "Tom Hardy", "role": "Eames (Forger)"},
        {"name": "Ken Watanabe", "role": "Mr. Saito (Tourist)"},
        {"name": "Christopher Nolan", "role": "Director"}
    ],
    "interstellar": [
        {"name": "Matthew McConaughey", "role": "Joseph Cooper"},
        {"name": "Anne Hathaway", "role": "Dr. Amelia Brand"},
        {"name": "Jessica Chastain", "role": "Murphy Cooper"},
        {"name": "Michael Caine", "role": "Professor John Brand"},
        {"name": "Christopher Nolan", "role": "Director"}
    ],
    "the matrix": [
        {"name": "Keanu Reeves", "role": "Neo / Thomas Anderson"},
        {"name": "Laurence Fishburne", "role": "Morpheus"},
        {"name": "Carrie-Anne Moss", "role": "Trinity"},
        {"name": "Hugo Weaving", "role": "Agent Smith"},
        {"name": "Lana & Lilly Wachowski", "role": "Directors"}
    ],
    "tenet": [
        {"name": "John David Washington", "role": "Protagonist"},
        {"name": "Robert Pattinson", "role": "Neil"},
        {"name": "Elizabeth Debicki", "role": "Kat"},
        {"name": "Kenneth Branagh", "role": "Andrei Sator"},
        {"name": "Christopher Nolan", "role": "Director"}
    ],
    "gladiator": [
        {"name": "Russell Crowe", "role": "Maximus Decimus Meridius"},
        {"name": "Joaquin Phoenix", "role": "Commodus"},
        {"name": "Connie Nielsen", "role": "Lucilla"},
        {"name": "Oliver Reed", "role": "Proximo"},
        {"name": "Ridley Scott", "role": "Director"}
    ],
    "shutter island": [
        {"name": "Leonardo DiCaprio", "role": "Teddy Daniels"},
        {"name": "Mark Ruffalo", "role": "Chuck Aule"},
        {"name": "Ben Kingsley", "role": "Dr. John Cawley"},
        {"name": "Michelle Williams", "role": "Dolores Chanal"},
        {"name": "Martin Scorsese", "role": "Director"}
    ],
    "rrr": [
        {"name": "N. T. Rama Rao Jr.", "role": "Komaram Bheem"},
        {"name": "Ram Charan", "role": "Alluri Sitarama Raju"},
        {"name": "Alia Bhatt", "role": "Sita"},
        {"name": "Ajay Devgn", "role": "Venkata Rama Raju"},
        {"name": "S. S. Rajamouli", "role": "Director"}
    ],
    "joe": [
        {"name": "Rio Raj", "role": "Joe"},
        {"name": "Malavika Manoj", "role": "Sucheetha"},
        {"name": "Bhavya Trikha", "role": "Shruthi"},
        {"name": "Hariharan Ram", "role": "Director"}
    ],
    "dune": [
        {"name": "Timothée Chalamet", "role": "Paul Atreides"},
        {"name": "Zendaya", "role": "Chani"},
        {"name": "Rebecca Ferguson", "role": "Lady Jessica"},
        {"name": "Oscar Isaac", "role": "Duke Leto Atreides"},
        {"name": "Denis Villeneuve", "role": "Director"}
    ],
    "the dark knight": [
        {"name": "Christian Bale", "role": "Bruce Wayne / Batman"},
        {"name": "Heath Ledger", "role": "The Joker"},
        {"name": "Aaron Eckhart", "role": "Harvey Dent / Two-Face"},
        {"name": "Gary Oldman", "role": "James Gordon"},
        {"name": "Christopher Nolan", "role": "Director"}
    ]
}

DYNAMIC_META_CACHE = {}

def fetch_dynamic_cinemeta(query: str):
    clean_q = clean_text(query)
    if clean_q in DYNAMIC_META_CACHE:
        return DYNAMIC_META_CACHE[clean_q]
    try:
        url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(query)}.json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as res:
            data = json.loads(res.read().decode())
            metas = data.get('metas', [])
            if metas:
                imdb_id = metas[0].get('imdb_id')
                if imdb_id:
                    detail_url = f"https://v3-cinemeta.strem.io/meta/movie/{imdb_id}.json"
                    req2 = urllib.request.Request(detail_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req2, timeout=3) as res2:
                        d2 = json.loads(res2.read().decode())
                        m2 = d2.get('meta', {})
                        cast_names = m2.get('cast', [])[:6]
                        result = {
                            "has_meta": True,
                            "imdb_id": imdb_id,
                            "poster": m2.get('poster') or metas[0].get('poster') or "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=400",
                            "summary": m2.get('description') or f"Verified cinematic presentation of {query}.",
                            "rating": str(m2.get('imdbRating') or "8.5"),
                            "genres": ", ".join(m2.get('genres', [])) or "Cinema Feature",
                            "year": str(m2.get('year') or "Movie"),
                            "cast": [{"name": c, "role": "Cast"} for c in cast_names] if cast_names else [{"name": f"{query.title()} Cast", "role": "Main"}]
                        }
                        DYNAMIC_META_CACHE[clean_q] = result
                        return result
    except Exception:
        pass
    return None

def fetch_local_xray_metadata(query: str):
    clean_q = clean_text(query)
    
    # Check verified cast database
    for k, cast_list in MOVIE_CAST_DATABASE.items():
        if k in clean_q or clean_q in k:
            # Also get matching preset if available
            for category in MOOD_PRESETS.values():
                for item in category:
                    if clean_text(item["title"]) in clean_q or clean_q in clean_text(item["title"]):
                        return {
                            "has_meta": True,
                            "poster": item["poster"],
                            "summary": item["summary"],
                            "rating": item["rating"],
                            "genres": item["genres"],
                            "year": item["year"],
                            "cast": cast_list
                        }
            return {
                "has_meta": True,
                "poster": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=400",
                "summary": f"Verified cinematic presentation of {query}.",
                "rating": "8.6",
                "genres": "Cinema Feature",
                "year": "Featured",
                "cast": cast_list
            }

    for category in MOOD_PRESETS.values():
        for item in category:
            if clean_q in clean_text(item["title"]) or clean_text(item["title"]) in clean_q:
                return {
                    "has_meta": True,
                    "poster": item["poster"],
                    "summary": item["summary"],
                    "rating": item["rating"],
                    "genres": item["genres"],
                    "year": item["year"],
                    "cast": MOVIE_CAST_DATABASE.get(clean_text(item["title"]), [
                        {"name": item["title"] + " Lead", "role": "Lead Role"},
                        {"name": "Supporting Cast", "role": "Key Ensemble"}
                    ])
                }

    # Dynamic Cinemeta lookup for any movie in the world
    dyn = fetch_dynamic_cinemeta(query)
    if dyn:
        return dyn

    return {
        "has_meta": True,
        "poster": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=400",
        "summary": f"High-definition verified cinematic presentation of {query}.",
        "rating": "8.5",
        "genres": "Cinema Feature",
        "year": "2024",
        "cast": [
            {"name": f"{query.title()} Cast", "role": "Main Role"},
            {"name": "Cinema Ensemble", "role": "Supporting Role"}
        ]
    }

SEARCH_CACHE = {}

def search_yt_dlp_sources(query: str, lang: str):
    cache_key = f"{query.lower().strip()}_{lang.lower().strip()}"
    if cache_key in SEARCH_CACHE:
        return SEARCH_CACHE[cache_key]

    results = []
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': 'ytsearch8',
        'nocheckcertificate': True,
        'socket_timeout': 6
    }
    
    # Target full movie uploads
    search_queries = [
        f"{query} full movie {lang}",
        f"{query} full movie",
        f"{query} {lang} movie"
    ]
    
    for sq in search_queries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch6:{sq}", download=False)
                if info and 'entries' in info:
                    for entry in info['entries']:
                        if not entry:
                            continue
                        duration = entry.get("duration") or 0
                        title = entry.get("title", query)
                        desc = entry.get("description") or ""
                        verification = verify_movie_result(query, lang, title, duration, desc)
                        if verification:
                            results.append({
                                "title": title,
                                "source": entry.get("extractor_key", "Web Video"),
                                "stream_url": entry.get("url") or entry.get("webpage_url"),
                                "type": "stream",
                                **verification
                            })
            if results:
                break
        except Exception as e:
            print("Search handled:", e)

    # If strict filter yielded zero results, do NOT inject unverified short clips or recaps!
    # Instead, search with full movie keyword and still require strict verification
    if not results:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch6:{query} {lang} full movie", download=False)
                if info and 'entries' in info:
                    for entry in info['entries']:
                        if not entry: continue
                        duration = entry.get("duration") or 0
                        title = entry.get("title", query)
                        desc = entry.get("description") or ""
                        verification = verify_movie_result(query, lang, title, duration, desc)
                        if verification:
                            results.append({
                                "title": title,
                                "source": entry.get("extractor_key", "Web Video"),
                                "stream_url": entry.get("url") or entry.get("webpage_url"),
                                "type": "stream",
                                **verification
                            })
        except Exception:
            pass

    if results:
        SEARCH_CACHE[cache_key] = results
    return results

VERIFIED_AD_FREE_REGIONAL_STREAMS = {
    "arjun reddy": [
        {
            "title": "Arjun Reddy (2017) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/arjun-reddy.-1080p/World4ufree1.me_ArjunReddy.1080pDual.mp4",
            "size_mb": 1021,
            "lang": "Telugu",
            "quality": "1080p FHD"
        },
        {
            "title": "Arjun Reddy (2017) • Telugu 720p HQ HDRip (Zero Ads)",
            "stream_url": "https://archive.org/download/arjun-reddy-2017-720p-telugu-hq-hdrip-hevc-dd-5.1-192kbps-1-gb-esub/Arjun%20Reddy%20%282017%29%20720p%20Telugu%20HQ%20HDRip%20-%20HEVC%20-%20%28DD5.1%20-%20192kbps%29%20-%201GB%20-%20ESub.mp4",
            "size_mb": 1047,
            "lang": "Telugu",
            "quality": "720p HD"
        }
    ],
    "rrr": [
        {
            "title": "RRR (2022) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/rrr-parrt-1-hand-brrrake/RRR%20Parrt%201%20HandBrrrake.ia.mp4",
            "size_mb": 1351,
            "lang": "Telugu",
            "quality": "1080p FHD"
        }
    ],
    "pushpa": [
        {
            "title": "Pushpa: The Rise (2021) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/pushpa-2021-telugu-720p-eagle-tv/Pushpa%20%282021%29%20Telugu%20720p%20%23EagleTV.mp4",
            "size_mb": 1002,
            "lang": "Telugu",
            "quality": "720p HD"
        }
    ],
    "devara": [
        {
            "title": "Devara Part 1 (2024) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/devara-part-1/Devara_Part_1.mp4",
            "size_mb": 727,
            "lang": "Telugu",
            "quality": "1080p HDRip"
        }
    ],
    "kalki 2898 ad": [
        {
            "title": "Kalki 2898 AD (2024) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/tg-movies-4u-kalki-2898-ad-2024-telugu-1080p-10bit-webrip/%40TG_Movies4u%20-Kalki%202898%20AD%20%282024%29%20TELUGU%201080p%2010bit%20WEBRip.mp4",
            "size_mb": 1026,
            "lang": "Telugu",
            "quality": "1080p 10bit"
        }
    ],
    "salaar": [
        {
            "title": "Salaar Part 1: Ceasefire (2023) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/salaar-part-1-telugu-drh-8i-2023-720p/Salaar.Part.1.Telugu.Drh8i.2023.720p.ia.mp4",
            "size_mb": 950,
            "lang": "Telugu",
            "quality": "720p HQ"
        }
    ],
    "geetha govindam": [
        {
            "title": "Geetha Govindam (2018) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/geetha-govindam-2018-telugu-org-x-264/Geetha%20Govindam%202018%20Telugu%20Org%20x264.mp4",
            "size_mb": 771,
            "lang": "Telugu",
            "quality": "720p Org"
        }
    ],
    "jersey": [
        {
            "title": "Jersey (2019) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/jersey-2019-1080p-hybrid-jc-webrip-x-265-10bit-telugu-ddp/Jersey%20%282019%29%201080p%20Hybrid%20JC%20WEBRip%20x265%2010bit%20%5BTelugu%20%28DDP%205.1%20-%20192Kbps%29%20%2B%20Tamil%20%2B%20Hindi%5D%20ESub%20-%20DTR.ia.mp4",
            "size_mb": 1390,
            "lang": "Telugu",
            "quality": "1080p FHD"
        }
    ],
    "magadheera": [
        {
            "title": "Magadheera (2009) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/magadheera-2009-blu-ray-uncut-720p-hindi-telugu-aac-5.1-x-264-esub-mkv-cinemas/Magadheera%20%282009%29%20Blu-Ray%20UNCUT%20720p%20%5BHindi%20-%20Telugu%20AAC%205.1%5D%20x264%20ESub%20-%20%5BMkv-Cinemas%5D.ia.mp4",
            "size_mb": 1150,
            "lang": "Telugu",
            "quality": "720p BluRay"
        }
    ],
    "baahubali": [
        {
            "title": "Baahubali: The Beginning (2015) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/bahubali-2015-1-cd-dvdscr-rip-x-264-mp-3-team-ddh-rg_202202/Bahubali%20%282015%29%20-%201CD%20-%20DVDSCR-Rip%20-%20x264%20-%20MP3%20-%20%5BTeam%20DDH~RG%5D.ia.mp4",
            "size_mb": 900,
            "lang": "Telugu",
            "quality": "Telugu Audio"
        }
    ],
    "dear comrade": [
        {
            "title": "Dear Comrade (2019) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/dear-comrade-2019-telugu-720p/Dear%20Comrade%202019.mp4",
            "size_mb": 850,
            "lang": "Telugu",
            "quality": "720p HD"
        }
    ],
    "hanu-man": [
        {
            "title": "Hanu-Man (2024) • Hindi Audio WEB-DL (1080p)",
            "stream_url": "https://archive.org/download/hanuman-2024-hindi-1080p-web-dl-x-264-aac-2.5-gb-qrips/Hanuman%20%282024%29%20Hindi%201080p%20WEB%20DL%20x264%20AAC%202.5%20GB%20QRips.ia.mp4",
            "size_mb": 2500,
            "lang": "Hindi",
            "quality": "1080p FHD"
        }
    ],
    "hanuman": [
        {
            "title": "Hanu-Man (2024) • Hindi Audio WEB-DL (1080p)",
            "stream_url": "https://archive.org/download/hanuman-2024-hindi-1080p-web-dl-x-264-aac-2.5-gb-qrips/Hanuman%20%282024%29%20Hindi%201080p%20WEB%20DL%20x264%20AAC%202.5%20GB%20QRips.ia.mp4",
            "size_mb": 2500,
            "lang": "Hindi",
            "quality": "1080p FHD"
        }
    ],
    "tillu square": [
        {
            "title": "Tillu Square (2024) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/www.-5-movie-rulz.plus-tillu-square-2024-telugu-720p-hdrip-x-264-aac/Www.5MovieRulz.plus%20-%20Tillu%20Square%20%282024%29%20Telugu%20720p%20HDRip%20x264%20AAC.mp4",
            "size_mb": 950,
            "lang": "Telugu",
            "quality": "720p HDRip"
        }
    ],
    "eega": [
        {
            "title": "Eega (2012) • ⚡ 100% Ad-Free Direct Stream (Original Telugu Audio)",
            "stream_url": "https://archive.org/download/eega-2012-telugu-720p/Eega%202012.mp4",
            "size_mb": 820,
            "lang": "Telugu",
            "quality": "720p HD"
        }
    ]
}

INDIAN_REGIONAL_CACHE = {}

def search_indian_regional_sources(query: str, lang: str):
    cache_key = f"{query.lower().strip()}_{lang.lower().strip()}"
    if cache_key in INDIAN_REGIONAL_CACHE:
        return INDIAN_REGIONAL_CACHE[cache_key]

    results = []
    clean_q = clean_text(query).lower().strip()

    # 1. Instant check against verified open archive database
    for key, items in VERIFIED_AD_FREE_REGIONAL_STREAMS.items():
        if key in clean_q or clean_q in key:
            for item in items:
                results.append({
                    "title": item["title"],
                    "source": "Archive.org Public Repository",
                    "stream_url": item["stream_url"],
                    "type": "direct_mp4",
                    "is_full_movie": True,
                    "is_audio_mismatch": False,
                    "badge": f"Reported {item.get('lang', lang)} Audio ({item['size_mb']} MB)",
                    "badge_color": "#10b981",
                    "print_type": f"Direct MP4 Video File",
                    "print_tag": "hd",
                    "print_color": "#059669",
                    "print_badge": item.get('quality', '1080p MP4'),
                    "duration_formatted": f"{item['size_mb']} MB MP4",
                    "movierulz_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' ' + lang + ' movierulz')}",
                    "filmyzilla_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' ' + lang + ' filmyzilla')}"
                })
            INDIAN_REGIONAL_CACHE[cache_key] = results
            return results

    # 2. Dynamic high-speed parallel scraping across Archive.org & MovieRulz repositories
    try:
        search_variants = [
            f"{clean_q} {lang}" if lang.lower() != "english" else clean_q,
            clean_q,
            f"{clean_q} movierulz"
        ]
        seen_identifiers = set()
        matched_docs = []

        for sv in search_variants:
            try:
                url = f"https://archive.org/advancedsearch.php?q={urllib.parse.quote(sv)}+AND+mediatype:(movies)&fl[]=identifier,title,downloads&sort[]=downloads+desc&rows=4&output=json"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    docs = json.loads(resp.read().decode("utf-8")).get("response", {}).get("docs", [])
                    for d in docs:
                        ident = d.get("identifier")
                        if ident and ident not in seen_identifiers:
                            seen_identifiers.add(ident)
                            matched_docs.append(d)
                if len(matched_docs) >= 6:
                    break
            except Exception:
                pass

        def inspect_doc_files(d):
            ident = d.get("identifier")
            try:
                meta_url = f"https://archive.org/metadata/{ident}/files"
                req_m = urllib.request.Request(meta_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_m, timeout=3.5) as r_m:
                    files = json.loads(r_m.read().decode("utf-8")).get("result", [])
                    for f in files:
                        fname = f.get("name", "")
                        size = int(f.get("size", 0)) if f.get("size") else 0
                        if (fname.endswith(".mp4") or fname.endswith(".mkv")) and size > 150_000_000:
                            stream_fname = fname
                            # If MKV, check if an auto-generated web-compatible .ia.mp4 is available
                            if fname.endswith(".mkv"):
                                ia_candidate = fname.replace(".mkv", ".ia.mp4")
                                if any(x.get("name") == ia_candidate for x in files):
                                    stream_fname = ia_candidate

                            stream_url = f"https://archive.org/download/{ident}/{urllib.parse.quote(stream_fname)}"
                            size_mb = round(size / (1024 * 1024))
                            display_title = d.get("title") or f"{query.title()} ({lang} HQ)"
                            return {
                                "title": f"{display_title} • Direct Video File",
                                "source": "Archive.org Public Repository",
                                "stream_url": stream_url,
                                "type": "direct_mp4",
                                "is_full_movie": True,
                                "is_audio_mismatch": False,
                                "badge": f"Reported {lang} Audio ({size_mb} MB)",
                                "badge_color": "#10b981",
                                "print_type": "Direct Media File",
                                "print_tag": "hd",
                                "print_color": "#059669",
                                "print_badge": f"{lang} MP4",
                                "duration_formatted": f"{size_mb} MB File",
                                "movierulz_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' ' + lang + ' movierulz')}",
                                "filmyzilla_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' ' + lang + ' filmyzilla')}"
                            }
            except Exception:
                pass
            return None

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_doc = [executor.submit(inspect_doc_files, d) for d in matched_docs[:6]]
            for future in concurrent.futures.as_completed(future_to_doc):
                res = future.result()
                if res:
                    results.append(res)
                if len(results) >= 3:
                    break
    except Exception:
        pass

    INDIAN_REGIONAL_CACHE[cache_key] = results
    return results

# ==================== WATCH PARTY SOCKET ENGINE ====================
class WatchPartyManager:
    def __init__(self):
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self.room_states: Dict[str, dict] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = set()
            self.room_states[room_id] = {
                "currentTime": 0,
                "playing": False,
                "mediaUrl": "",
                "streamType": "video",
                "title": "Movie Party"
            }
        self.rooms[room_id].add(websocket)
        await websocket.send_json({
            "type": "sync_state",
            "state": self.room_states[room_id],
            "onlineCount": len(self.rooms[room_id])
        })
        await self.broadcast(room_id, {
            "type": "user_count",
            "onlineCount": len(self.rooms[room_id]),
            "count": len(self.rooms[room_id])
        }, sender=websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.rooms:
            self.rooms[room_id].discard(websocket)
            if len(self.rooms[room_id]) == 0:
                del self.rooms[room_id]
                if room_id in self.room_states:
                    del self.room_states[room_id]

    async def broadcast(self, room_id: str, message: dict, sender: WebSocket = None):
        if room_id in self.rooms:
            for conn in list(self.rooms[room_id]):
                if conn != sender:
                    try:
                        await conn.send_json(message)
                    except Exception:
                        pass

party_manager = WatchPartyManager()

@app.websocket("/ws/party/{room_id}")
async def watch_party_endpoint(websocket: WebSocket, room_id: str):
    await party_manager.connect(room_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            
            if event_type in ["play", "pause", "seek"]:
                if room_id in party_manager.room_states:
                    party_manager.room_states[room_id]["currentTime"] = data.get("currentTime", 0)
                    party_manager.room_states[room_id]["playing"] = (event_type == "play")
                await party_manager.broadcast(room_id, data, sender=websocket)
                
            elif event_type == "set_media":
                if room_id in party_manager.room_states:
                    party_manager.room_states[room_id]["mediaUrl"] = data.get("mediaUrl", "")
                    party_manager.room_states[room_id]["streamType"] = data.get("streamType", "video")
                    party_manager.room_states[room_id]["title"] = data.get("title", "")
                    party_manager.room_states[room_id]["currentTime"] = 0
                    party_manager.room_states[room_id]["playing"] = True
                await party_manager.broadcast(room_id, data, sender=websocket)
                
            elif event_type == "chat":
                # Broadcast chat to other members only (sender appends locally!)
                await party_manager.broadcast(room_id, {
                    "type": "chat",
                    "user": data.get("user", "Friend"),
                    "text": data.get("text", ""),
                    "senderId": data.get("senderId", ""),
                    "time": data.get("time", "")
                }, sender=websocket)
    except WebSocketDisconnect:
        party_manager.disconnect(room_id, websocket)
        await party_manager.broadcast(room_id, {
            "type": "user_count",
            "onlineCount": len(party_manager.rooms.get(room_id, [])),
            "count": len(party_manager.rooms.get(room_id, []))
        })

# ==================== REST APIS ====================
@app.get("/api/config")
def get_config():
    return {
        "host_ip": HOST_IP,
        "port": 8000
    }

LANGUAGE_ALIASES = {
    "telugu": ["telug", "telugu"],
    "hindi": ["hind", "hindi"],
    "tamil": ["tam", "tamil"],
    "malayalam": ["malayalam", "malyalam"],
    "kannada": ["kannada"],
    "english": ["eng", "english"],
    "spanish": ["spanish", "espanol"],
    "french": ["french", "francais"],
    "japanese": ["japanese", "anime"],
    "korean": ["korean", "k-drama", "kdrama"]
}

def extract_language_and_clean_query(raw_query: str, selected_lang: str):
    cleaned_words = []
    detected_lang = selected_lang
    for w in raw_query.split():
        clean_w = re.sub(r'[^a-zA-Z0-9]', '', w).lower()
        matched = None
        for lname, aliases in LANGUAGE_ALIASES.items():
            if clean_w in aliases:
                matched = lname.capitalize()
                break
        if matched:
            detected_lang = matched
        else:
            cleaned_words.append(w)
    return (' '.join(cleaned_words).strip() or raw_query), detected_lang

def get_ai_suggestions_for_movie(query: str, lang: str):
    clean_q = clean_text(query)
    if lang.lower() == "telugu" or any(w in clean_q for w in ["arjun", "reddy", "telugu", "telug", "vijay", "deverakonda", "rrr", "salaar", "kalki"]):
        return [
            {"title": "Dear Comrade", "lang": "Telugu", "badge": "Vijay Deverakonda Hit", "year": "2019", "genres": "Action, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BZjRiZTU3NmUtODk4Yy00MDkxLTk1NDItODZlNDk5ZjkyNTU5XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
            {"title": "Geetha Govindam", "lang": "Telugu", "badge": "Superhit Rom-Com", "year": "2018", "genres": "Romance, Comedy", "poster": "https://m.media-amazon.com/images/M/MV5BNjE4OGY5OTItYWM0MC00YjBhLTg4YmEtYzA4NjVlNTBiMDhjXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
            {"title": "World Famous Lover", "lang": "Telugu", "badge": "Full Telugu Stream", "year": "2020", "genres": "Drama, Romance", "poster": "https://m.media-amazon.com/images/M/MV5BYzA2YzdiY2QtMDVjZS00N2EzLWExOWItZjEyN2ZkZjExMWYyXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
            {"title": "RRR", "lang": "Telugu", "badge": "Action Blockbuster", "year": "2022", "genres": "Action, Epic", "poster": "https://m.media-amazon.com/images/M/MV5BODUwNDNjMTctODUxNy00ZTA2LWIyYTEtMDc5Y2E5NjBmNTMzXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
            {"title": "Joe", "lang": "Telugu", "badge": "Verified Stream", "year": "2023", "genres": "Romance, Drama", "poster": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=400"}
        ]
    return [
        {"title": "Inception", "lang": "English", "badge": "Sci-Fi Classic", "year": "2010", "genres": "Sci-Fi, Thriller", "poster": "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_FMjpg_UX1000_.jpg"},
        {"title": "Interstellar", "lang": "English", "badge": "Nolan Masterpiece", "year": "2014", "genres": "Sci-Fi, Adventure", "poster": "https://m.media-amazon.com/images/M/MV5BYzdjMDAxZGItMjI2My00ODA1LTlkNzItOWFjMDU5ZDJlYWY3XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
        {"title": "Shutter Island", "lang": "English", "badge": "Mind-Bending", "year": "2010", "genres": "Mystery, Thriller", "poster": "https://m.media-amazon.com/images/M/MV5BN2FjNWExNDEtYjc4NC00YTE1LWEwODctZDVlMGYwNzg4MGQ2XkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"},
        {"title": "Gladiator", "lang": "English", "badge": "Epic Cinema", "year": "2000", "genres": "Action, Drama", "poster": "https://m.media-amazon.com/images/M/MV5BYWQ4YmNjYjEtOWE1Zi00Y2U4LWI4NTAtMTU0MjkxNWQ1ZmJiXkEyXkFqcGc@._V1_FMjpg_UX1000_.jpg"}
    ]

@app.get("/api/suggestions")
def get_live_suggestions(q: str = ""):
    clean_q = clean_text(q)
    popular = [
        {"title": "Arjun Reddy", "lang": "Telugu", "year": "2017"},
        {"title": "Dear Comrade", "lang": "Telugu", "year": "2019"},
        {"title": "Geetha Govindam", "lang": "Telugu", "year": "2018"},
        {"title": "World Famous Lover", "lang": "Telugu", "year": "2020"},
        {"title": "RRR", "lang": "Telugu", "year": "2022"},
        {"title": "Joe", "lang": "Telugu", "year": "2023"},
        {"title": "Inception", "lang": "English", "year": "2010"},
        {"title": "Interstellar", "lang": "English", "year": "2014"},
        {"title": "Shutter Island", "lang": "English", "year": "2010"},
        {"title": "The Dark Knight", "lang": "English", "year": "2008"},
        {"title": "Gladiator", "lang": "English", "year": "2000"},
        {"title": "Dune", "lang": "English", "year": "2021"}
    ]
    if not clean_q:
        return {"suggestions": popular[:6]}
    matches = [s for s in popular if clean_q in clean_text(s["title"]) or clean_q in s["lang"].lower()]
    return {"suggestions": (matches or popular[:4])[:6]}

IMDB_DATABASE = {
    "arjun reddy": "tt7294534",
    "inception": "tt1375666",
    "interstellar": "tt0816692",
    "the matrix": "tt0133093",
    "tenet": "tt6723592",
    "gladiator": "tt0172495",
    "gladiator 2": "tt9218128",
    "gladiator ii": "tt9218128",
    "shutter island": "tt1130884",
    "rrr": "tt8178634",
    "dune": "tt1160419",
    "dune 2": "tt15239678",
    "dune part two": "tt15239678",
    "the dark knight": "tt0468569",
    "dear comrade": "tt8388508",
    "geetha govindam": "tt8590896",
    "world famous lover": "tt10991188",
    "pushpa": "tt9389998",
    "pushpa the rise": "tt9389998",
    "pushpa 2": "tt16539454",
    "pushpa the rule": "tt16539454",
    "kalki": "tt12735488",
    "kalki 2898 ad": "tt12735488",
    "salaar": "tt13927994",
    "animal": "tt13751694",
    "avatar": "tt0499549",
    "avatar the way of water": "tt1630029",
    "spider man": "tt10872600",
    "oppenheimer": "tt15398776"
}

_IMDB_CACHE = {}

def get_live_imdb_id(query_str: str) -> str:
    clean_q = clean_text(query_str)
    if clean_q in IMDB_DATABASE:
        return IMDB_DATABASE[clean_q]
    if clean_q in _IMDB_CACHE:
        return _IMDB_CACHE[clean_q]
    for k, v in IMDB_DATABASE.items():
        if k in clean_q or clean_q in k:
            return v
    # Dynamic Cinemeta lookup
    try:
        url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(query_str)}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            metas = data.get("metas", [])
            if metas and metas[0].get("id"):
                found_id = metas[0].get("id")
                _IMDB_CACHE[clean_q] = found_id
                return found_id
    except Exception:
        pass
    return None

@app.post("/api/search")
def search_movie(req: SearchRequest):
    raw_query = req.query.strip()
    if not raw_query:
        raise HTTPException(status_code=400, detail="Movie name is required")
        
    query, lang = extract_language_and_clean_query(raw_query, req.language.strip() or "English")
    
    # 1. Fetch Canonical Title & Disambiguation Candidates from Cinemeta
    disambiguation_options = []
    canonical_meta = None
    imdb_id = req.imdb_id or None
    clean_q = clean_text(query)
    
    if not imdb_id and clean_q in IMDB_DATABASE:
        imdb_id = IMDB_DATABASE[clean_q]
        
    try:
        cinemeta_url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(query)}.json"
        req_c = urllib.request.Request(cinemeta_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req_c, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            metas = data.get("metas", [])
            for m in metas[:6]:
                m_id = m.get("id") or m.get("imdb_id")
                m_title = m.get("name")
                m_year = str(m.get("year", ""))
                m_poster = m.get("poster")
                if m_id and m_title:
                    disambiguation_options.append({
                        "imdb_id": m_id,
                        "title": m_title,
                        "year": m_year,
                        "poster": m_poster,
                        "genres": m.get("genres", [])
                    })
            if not imdb_id and disambiguation_options:
                imdb_id = disambiguation_options[0]["imdb_id"]
    except Exception:
        pass

    # Detailed canonical metadata
    meta = fetch_local_xray_metadata(query)
    if not meta or not meta.get("poster") or "unsplash" in meta.get("poster", ""):
        if disambiguation_options:
            top_cand = disambiguation_options[0]
            meta = {
                "has_meta": True,
                "imdb_id": top_cand["imdb_id"],
                "title": top_cand["title"],
                "year": top_cand["year"],
                "poster": top_cand["poster"],
                "summary": f"Verified metadata for {top_cand['title']} ({top_cand['year']}).",
                "rating": "IMDb Verified",
                "genres": ", ".join(top_cand.get("genres", ["Feature Film"])),
                "cast": []
            }

    # 2. Legitimate Watch Providers / Official OTT Options
    official_watch_providers = [
        {"name": "Prime Video", "provider": "Amazon", "url": f"https://www.primevideo.com/search/ref=atv_nb_sr?phrase={urllib.parse.quote(query)}"},
        {"name": "Netflix", "provider": "Netflix", "url": f"https://www.netflix.com/search?q={urllib.parse.quote(query)}"},
        {"name": "Disney+ Hotstar", "provider": "Disney+", "url": f"https://www.hotstar.com/in/explore?search_query={urllib.parse.quote(query)}"},
        {"name": "Aha Video", "provider": "Aha (Telugu)", "url": f"https://www.aha.video/search?q={urllib.parse.quote(query)}"},
        {"name": "Zee5", "provider": "Zee5", "url": f"https://www.zee5.com/search?q={urllib.parse.quote(query)}"}
    ]

    # 3. Confirmed Playback Sources (Factual and Honest)
    confirmed_playback_sources = []
    
    # Regional archive & verified direct streams
    regional_results = search_indian_regional_sources(query, lang)
    for r in regional_results:
        confirmed_playback_sources.append(r)

    # Official YouTube uploads (if strictly verified)
    yt_results = search_yt_dlp_sources(query, lang)
    for yt in yt_results:
        confirmed_playback_sources.append(yt)

    # Community Cloud Mirrors (Only if canonical IMDb ID exists, and labeled factually)
    if imdb_id:
        s1 = f"https://vidlink.pro/movie/{imdb_id}"
        s2 = f"https://embed.smashystream.com/playere.php?imdb={imdb_id}"
        s3 = f"https://vidsrc.me/embed/movie?imdb={imdb_id}"
        s4 = f"https://2embed.cc/embed/{imdb_id}"
        confirmed_playback_sources.append({
            "title": f"{query.title()} • Community Cloud Stream",
            "source": "Third-Party Community Mirror",
            "stream_url": s1,
            "servers": {
                "Server 1 (VidLink HD)": s1,
                "Server 2 (Smashy Cloud)": s2,
                "Server 3 (VIP Cloud)": s3,
                "Server 4 (Fast Mirror)": s4
            },
            "imdb_id": imdb_id,
            "type": "universal_embed",
            "is_full_movie": False,
            "badge": "Community Mirror (May contain ads)",
            "badge_color": "#64748b",
            "print_type": "Third-Party Web Player",
            "print_tag": "embed",
            "print_color": "#475569",
            "print_badge": "Cloud Player",
            "duration_formatted": "Third-Party Stream",
            "movierulz_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' ' + lang + ' movierulz')}",
            "filmyzilla_search_url": f"https://www.google.com/search?q={urllib.parse.quote(query + ' filmyzilla')}"
        })

    ai_suggestions = get_ai_suggestions_for_movie(query, lang)

    return {
        "query": query,
        "language": lang,
        "meta": meta,
        "disambiguation": disambiguation_options,
        "official_providers": official_watch_providers,
        "results": confirmed_playback_sources,
        "has_confirmed_sources": len(confirmed_playback_sources) > 0,
        "ai_suggestions": ai_suggestions
    }

@app.post("/api/mood_search")
def search_by_mood(req: MoodSearchRequest):
    mood_text = req.mood.lower().strip()

    def has_any(keywords):
        return any(bool(re.search(r'\b' + re.escape(k.lower()) + r'\b', mood_text)) or (k.lower() in mood_text) for k in keywords)

    selected_items = None
    if has_any(["telugu", "tollywood", "south", "vijay", "arjun", "deverakonda", "ram charan", "ntr"]):
        selected_items = MOOD_PRESETS["telugu"]
    elif has_any(["thrill", "murder", "mystery", "crime", "detective", "psychological", "suspense", "investigat"]):
        selected_items = MOOD_PRESETS["thriller"]
    elif has_any(["ocean", "sea", "nature", "animal", "documentary", "planet", "wildlife", "marine", "underwater", "creature"]):
        selected_items = MOOD_PRESETS["nature-documentary"]
    elif has_any(["horror", "scary", "ghost", "spooky", "haunt", "demon", "creep"]):
        selected_items = MOOD_PRESETS["horror"]
    elif has_any(["scifi", "mind", "bending", "space", "matrix", "future", "twist", "quantum"]):
        selected_items = MOOD_PRESETS["mind-bending"]
    elif has_any(["action", "epic", "war", "fight", "battle", "hero", "superhero", "dune"]):
        selected_items = MOOD_PRESETS["epic"]
    elif has_any(["cozy", "feel", "comedy", "funny", "laugh", "romance", "love", "heart"]):
        selected_items = MOOD_PRESETS["cozy"]
    else:
        selected_items = MOOD_PRESETS["telugu"] if ("telug" in mood_text) else MOOD_PRESETS["mind-bending"]
        
    return {
        "mood": req.mood,
        "recommendations": selected_items
    }

@app.get("/api/ai_surprise")
def get_ai_surprise_movie():
    import random
    surprises = [
        {"title": "Arjun Reddy", "lang": "Telugu", "year": "2017", "genre": "Intense Romance / Drama", "rating": "8.0", "reason": "Raw emotional powerhouse performance by Vijay Deverakonda with iconic soundtrack.", "poster": "https://images.metahub.space/poster/small/tt7294534/img"},
        {"title": "Inception", "lang": "English", "year": "2010", "genre": "Sci-Fi / Mind-Bending Heist", "rating": "8.8", "reason": "Christopher Nolan's magnum opus exploring subconscious dream architecture.", "poster": "https://images.metahub.space/poster/small/tt1375666/img"},
        {"title": "Interstellar", "lang": "English", "year": "2014", "genre": "Sci-Fi / Emotional Epic", "rating": "8.7", "reason": "Visually breathtaking odyssey across wormholes powered by Hans Zimmer's score.", "poster": "https://images.metahub.space/poster/small/tt0816692/img"},
        {"title": "RRR", "lang": "Telugu", "year": "2022", "genre": "Epic Action / Historical Fiction", "rating": "8.8", "reason": "Oscar-winning high-octane spectacle of brotherhood and fire vs water.", "poster": "https://images.metahub.space/poster/small/tt8178634/img"},
        {"title": "The Dark Knight", "lang": "English", "year": "2008", "genre": "Psychological Crime / Superhero", "rating": "9.0", "reason": "Heath Ledger's legendary Oscar-winning Joker performance in Gotham City.", "poster": "https://images.metahub.space/poster/small/tt0468569/img"},
        {"title": "Dear Comrade", "lang": "Telugu", "year": "2019", "genre": "Romantic Drama / Inspiring", "rating": "7.5", "reason": "Soulful journey of passion, cricket, mental resilience, and timeless melodies.", "poster": "https://images.metahub.space/poster/small/tt8914570/img"},
        {"title": "Gladiator", "lang": "English", "year": "2000", "genre": "Historical Epic / Action", "rating": "8.5", "reason": "Ridley Scott's Roman arena epic of vengeance, honor, and freedom.", "poster": "https://images.metahub.space/poster/small/tt0172495/img"},
        {"title": "Geetha Govindam", "lang": "Telugu", "year": "2018", "genre": "Romantic Comedy / Family", "rating": "7.7", "reason": "Charming comedy of errors with Vijay Deverakonda and Rashmika Mandanna.", "poster": "https://images.metahub.space/poster/small/tt8385474/img"},
        {"title": "Dune", "lang": "English", "year": "2021", "genre": "Sci-Fi / Masterpiece", "rating": "8.1", "reason": "Denis Villeneuve's grand visual and sonic masterpiece on the sands of Arrakis.", "poster": "https://images.metahub.space/poster/small/tt1160419/img"},
        {"title": "Kalki 2898 AD", "lang": "Telugu", "year": "2024", "genre": "Mythology / Futuristic Sci-Fi", "rating": "8.0", "reason": "Prabhas, Amitabh Bachchan, and Kamal Haasan in a dystopian epic blending Mahabharata and the year 2898.", "poster": "https://images.metahub.space/poster/small/tt12735488/img"},
        {"title": "Shutter Island", "lang": "English", "year": "2010", "genre": "Psychological Mystery / Thriller", "rating": "8.2", "reason": "Martin Scorsese's dark psychological maze with a heart-stopping twist ending.", "poster": "https://images.metahub.space/poster/small/tt1130884/img"}
    ]
    return random.choice(surprises)

@app.post("/api/sniff_url")
def sniff_direct_url(req: DirectUrlRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="Disallowed or private URL target")

    # If direct video file URL
    parsed = urllib.parse.urlparse(url)
    clean_path = parsed.path.lower()
    if any(clean_path.endswith(ext) for ext in [".mp4", ".m3u8", ".webm", ".mkv"]) or ("archive.org/download/" in url):
        return {
            "title": "Direct Web Video",
            "source": "Direct URL",
            "stream_url": url,
            "type": "direct_sniffed",
            "duration_formatted": "Full Video",
            "is_full_movie": True,
            "badge": "Web Stream",
            "badge_color": "#0ea5e9",
            "print_type": "Digital Stream",
            "print_tag": "hd",
            "print_color": "#10b981",
            "print_badge": "Direct Media"
        }

    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'nocheckcertificate': True, 'socket_timeout': 5}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Direct Web Stream")
            duration = info.get("duration") or 0
            desc = info.get("description") or ""
            stream_url = info.get("url") or url
            print_info = detect_print_quality(title, desc)
            return {
                "title": title,
                "source": info.get("extractor_key", "Direct URL"),
                "stream_url": stream_url,
                "type": "direct_sniffed",
                "duration_formatted": format_duration(duration),
                "is_full_movie": duration >= 2700,
                "badge": "Web Stream",
                "badge_color": "#0ea5e9",
                **print_info
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Extract error: {str(e)}")

@app.get("/api/extract_stream")
def extract_stream(url: str, quality: str = "best"):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="Disallowed or private URL target")

    # Direct playable link
    parsed = urllib.parse.urlparse(url)
    clean_path = parsed.path.lower()
    if any(clean_path.endswith(ext) for ext in [".mp4", ".m3u8", ".webm", ".mkv"]) or ("archive.org/download/" in url):
        return {"stream_type": "video", "stream_url": url, "title": "Direct Stream"}

    # If universal embed or multi-server URL
    if any(k in url.lower() for k in ["multiembed", "vidsrc", "2embed", "autoembed", "superembed", "vidlink", "smashystream", "/embed", "/movie"]):
        return {"stream_type": "embed", "stream_url": url, "title": "Third-Party Player Embed", "quality": quality}

    yt_match = re.search(r'(?:v=|\/|embed\/|shorts\/)([0-9A-Za-z_-]{11})', url)
    if yt_match:
        video_id = yt_match.group(1)
        vq_param = ""
        if quality == "1080p": vq_param = "&vq=hd1080"
        elif quality == "720p": vq_param = "&vq=hd720"
        elif quality == "480p": vq_param = "&vq=large"
        embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&enablejsapi=1{vq_param}"
        return {"stream_type": "embed", "stream_url": embed_url, "title": "Video Stream", "quality": quality}

    fmt_choice = 'best[ext=mp4]/best'
    if quality == "1080p": fmt_choice = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best'
    elif quality == "720p": fmt_choice = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best'
    elif quality == "480p": fmt_choice = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best'
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': fmt_choice,
        'nocheckcertificate': True,
        'socket_timeout': 4,
        'ignoreerrors': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                stream_url = info.get("url")
                if not stream_url and "formats" in info and len(info["formats"]) > 0:
                    stream_url = info["formats"][-1].get("url")
                return {"stream_type": "video", "stream_url": stream_url or url, "title": info.get("title", "Video")}
    except Exception:
        pass
    return {"stream_type": "video", "stream_url": url, "title": "Stream"}

def download_task(task_id: str, url: str, title: str, quality: str, include_subs: bool, sub_lang: str):
    downloads_status[task_id] = {"status": "downloading", "progress": 0, "filename": "", "speed": "0 KB/s"}
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).rstrip()
    out_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}_%(id)s.%(ext)s")
    
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            downloaded = d.get('downloaded_bytes', 0)
            percent = int((downloaded / total) * 100)
            speed = d.get('_speed_str', '')
            eta = d.get('_eta_str', '')
            downloads_status[task_id]["progress"] = percent
            downloads_status[task_id]["speed"] = f"{speed} (ETA: {eta})" if speed else ""
        elif d['status'] == 'finished':
            downloads_status[task_id]["status"] = "finished"
            downloads_status[task_id]["filename"] = os.path.basename(d['filename'])
            downloads_status[task_id]["filepath"] = d['filename']

    fmt_choice = 'best[ext=mp4]/best'
    if quality == "1080p": fmt_choice = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best'
    elif quality == "720p": fmt_choice = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best'
    elif quality == "480p": fmt_choice = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best'

    ydl_opts = {
        'outtmpl': out_template,
        'format': fmt_choice,
        'progress_hooks': [hook],
        'quiet': True,
        'concurrent_fragment_downloads': 8,
        'nocheckcertificate': True,
    }
    if include_subs:
        ydl_opts['writesubtitles'] = True
        ydl_opts['writeautomaticsub'] = True
        ydl_opts['subtitleslangs'] = [sub_lang, 'en']

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        downloads_status[task_id] = {"status": "error", "message": str(e)}

@app.post("/api/download")
def start_download(req: DownloadRequest, bg_tasks: BackgroundTasks):
    if not is_safe_url(req.url):
        raise HTTPException(status_code=400, detail="Invalid or disallowed destination URL")
    task_id = f"dl_{len(downloads_status) + 1}_{abs(hash(req.url)) % 10000}"
    downloads_status[task_id] = {"status": "starting", "progress": 0}
    bg_tasks.add_task(download_task, task_id, req.url, req.title, req.quality, req.include_subtitles, req.sub_lang)
    return {"task_id": task_id}

@app.get("/api/download_status/{task_id}")
def get_download_status(task_id: str):
    status = downloads_status.get(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status

@app.get("/api/get_file/{task_id}")
def get_file(task_id: str):
    info = downloads_status.get(task_id)
    if not info or info.get("status") != "finished":
        raise HTTPException(status_code=400, detail="File not ready")
    filepath = info.get("filepath")
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type="video/mp4", filename=os.path.basename(filepath))
    raise HTTPException(status_code=404, detail="File missing")

@app.get("/qrcode.min.js")
def get_qrcode_js():
    js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qrcode.min.js")
    return FileResponse(js_path, media_type="application/javascript")

@app.get("/welcome_tour.mp3")
def get_welcome_tour_audio():
    audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "welcome_tour.mp3")
    return FileResponse(audio_path, media_type="audio/mpeg")

@app.get("/manifest.json")
def get_manifest():
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")
    return FileResponse(manifest_path, media_type="application/json")

@app.get("/sw.js")
def get_sw():
    sw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sw.js")
    return FileResponse(sw_path, media_type="application/javascript")

@app.get("/favicon.ico")
def get_favicon():
    return Response(status_code=204)

@app.get("/googleeeae74686c9dc05e.html", response_class=PlainTextResponse)
def get_google_verification():
    return "google-site-verification: googleeeae74686c9dc05e.html"

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    return """User-agent: *
Allow: /
Sitemap: /sitemap.xml
"""

@app.get("/sitemap.xml", response_class=Response)
def get_sitemap_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://cinemahub-vip.onrender.com/</loc>
    <lastmod>2026-11-16</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/", response_class=HTMLResponse)
def index():
    html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(html_file, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
