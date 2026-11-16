import urllib.request
import urllib.parse
import json
import time
import concurrent.futures
import ssl

BASE_URL = "https://cinemahub-vip.onrender.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

test_results = []

def record(test_id, category, name, passed, duration_ms, details=""):
    test_results.append({
        "id": test_id,
        "category": category,
        "name": name,
        "passed": passed,
        "duration_ms": round(duration_ms, 2),
        "details": details
    })
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] #{test_id:03d} [{category}] {name} ({round(duration_ms)}ms) - {details[:60]}")

# ==================== 1. STATIC ASSETS & CORE ROUTES (1-10) ====================
def test_static_route(test_id, path, expected_status=200, check_str=None):
    start = time.time()
    try:
        req = urllib.request.Request(f"{BASE_URL}{path}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            body = resp.read().decode('utf-8', errors='ignore')
            passed = resp.status == expected_status
            if check_str:
                passed = passed and (check_str in body)
            details = f"HTTP {resp.status}, size: {len(body)} bytes"
            if check_str and check_str not in body:
                details += f" (missing '{check_str}')"
            record(test_id, "Core Routes", f"GET {path}", passed, dur, details)
    except urllib.error.HTTPError as e:
        dur = (time.time() - start) * 1000
        passed = (e.code == expected_status)
        details = f"HTTP {e.code} (Expected {expected_status})"
        record(test_id, "Core Routes", f"GET {path}", passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "Core Routes", f"GET {path}", False, dur, str(e))

# ==================== 2. API ENDPOINT TESTS (11-25) ====================
def test_post_api(test_id, endpoint, payload, validator):
    start = time.time()
    try:
        req = urllib.request.Request(
            f"{BASE_URL}{endpoint}",
            data=json.dumps(payload).encode('utf-8'),
            headers={**HEADERS, "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            data = json.loads(resp.read().decode('utf-8'))
            passed, msg = validator(data, resp.status)
            record(test_id, "API Endpoints", f"POST {endpoint}", passed, dur, msg)
    except urllib.error.HTTPError as e:
        dur = (time.time() - start) * 1000
        try:
            data = json.loads(e.read().decode('utf-8'))
        except Exception:
            data = None
        passed, msg = validator(data, e.code)
        record(test_id, "API Endpoints", f"POST {endpoint}", passed, dur, msg)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "API Endpoints", f"POST {endpoint}", False, dur, str(e))

def test_get_api(test_id, endpoint, validator):
    start = time.time()
    try:
        req = urllib.request.Request(f"{BASE_URL}{endpoint}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            data = json.loads(resp.read().decode('utf-8'))
            passed, msg = validator(data, resp.status)
            record(test_id, "API Endpoints", f"GET {endpoint}", passed, dur, msg)
    except urllib.error.HTTPError as e:
        dur = (time.time() - start) * 1000
        try:
            data = json.loads(e.read().decode('utf-8'))
        except Exception:
            data = None
        passed, msg = validator(data, e.code)
        record(test_id, "API Endpoints", f"GET {endpoint}", passed, dur, msg)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "API Endpoints", f"GET {endpoint}", False, dur, str(e))

# ==================== 3. SEARCH MATRIX (26-75: 50 Movies across Languages) ====================
MOVIE_TEST_SET = [
    # Telugu (15)
    ("RRR", "Telugu"),
    ("Arjun Reddy", "Telugu"),
    ("Pushpa", "Telugu"),
    ("Kalki 2898 AD", "Telugu"),
    ("Devara", "Telugu"),
    ("Salaar", "Telugu"),
    ("Geetha Govindam", "Telugu"),
    ("Dear Comrade", "Telugu"),
    ("Hanu-Man", "Telugu"),
    ("Guntur Kaaram", "Telugu"),
    ("Tillu Square", "Telugu"),
    ("Waltair Veerayya", "Telugu"),
    ("Eega", "Telugu"),
    ("Baahubali", "Telugu"),
    ("World Famous Lover", "Telugu"),
    # Hindi / Bollywood (10)
    ("Stree 2", "Hindi"),
    ("Jawan", "Hindi"),
    ("Pathaan", "Hindi"),
    ("Animal", "Hindi"),
    ("Dangal", "Hindi"),
    ("3 Idiots", "Hindi"),
    ("Sholay", "Hindi"),
    ("Kabir Singh", "Hindi"),
    ("Brahmastra", "Hindi"),
    ("Fighter", "Hindi"),
    # Hollywood / English (15)
    ("Inception", "English"),
    ("Interstellar", "English"),
    ("The Matrix", "English"),
    ("Tenet", "English"),
    ("Gladiator 2", "English"),
    ("Oppenheimer", "English"),
    ("Dune", "English"),
    ("The Dark Knight", "English"),
    ("Avatar", "English"),
    ("Titanic", "English"),
    ("Spider-Man", "English"),
    ("Shutter Island", "English"),
    ("Avengers Endgame", "English"),
    ("Joker", "English"),
    ("Fight Club", "English"),
    # Tamil / Malayalam / Regional (10)
    ("Leo", "Tamil"),
    ("Jailer", "Tamil"),
    ("Vikram", "Tamil"),
    ("Ponniyin Selvan", "Tamil"),
    ("Master", "Tamil"),
    ("Manjummel Boys", "Malayalam"),
    ("Aavesham", "Malayalam"),
    ("Premalu", "Malayalam"),
    ("Kantara", "Kannada"),
    ("KGF Chapter 2", "Kannada")
]

def test_search_movie(test_id, movie_name, lang):
    start = time.time()
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/search",
            data=json.dumps({"query": movie_name, "language": lang}).encode('utf-8'),
            headers={**HEADERS, "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            data = json.loads(resp.read().decode('utf-8'))
            results = data.get("results", [])
            passed = len(results) > 0
            
            # Check if Universal card or direct MP4 exists
            has_universal = any("Universal Cinema Server" in r.get("title", "") for r in results)
            has_regional = any("MovieRulz" in r.get("source", "") for r in results)
            first_title = results[0].get("title", "") if results else "None"
            
            details = f"Found {len(results)} results | Top: {first_title[:30]} | Universal: {has_universal} | Regional: {has_regional}"
            record(test_id, f"Search ({lang})", f"Search '{movie_name}'", passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, f"Search ({lang})", f"Search '{movie_name}'", False, dur, str(e))

# ==================== 4. EMBED STREAMING PROVIDER AVAILABILITY (76-90) ====================
EMBED_PROVIDERS = [
    ("VidLink HD (Arjun Reddy)", "https://vidlink.pro/movie/tt7294534"),
    ("Smashy Cloud (Arjun Reddy)", "https://embed.smashystream.com/playere.php?imdb=tt7294534"),
    ("VIP Cloud (Arjun Reddy)", "https://vidsrc.me/embed/movie?imdb=tt7294534"),
    ("Fast Mirror (Arjun Reddy)", "https://2embed.cc/embed/tt7294534"),
    ("VidLink HD (RRR)", "https://vidlink.pro/movie/tt8178634"),
    ("Smashy Cloud (RRR)", "https://embed.smashystream.com/playere.php?imdb=tt8178634"),
    ("VIP Cloud (RRR)", "https://vidsrc.me/embed/movie?imdb=tt8178634"),
    ("Fast Mirror (RRR)", "https://2embed.cc/embed/tt8178634"),
    ("VidLink HD (Inception)", "https://vidlink.pro/movie/tt1375666"),
    ("Smashy Cloud (Inception)", "https://embed.smashystream.com/playere.php?imdb=tt1375666"),
    ("VIP Cloud (Inception)", "https://vidsrc.me/embed/movie?imdb=tt1375666"),
    ("Fast Mirror (Inception)", "https://2embed.cc/embed/tt1375666"),
    ("VidLink HD (Kalki 2898 AD)", "https://vidlink.pro/movie/tt12735488"),
    ("Smashy Cloud (Kalki 2898 AD)", "https://embed.smashystream.com/playere.php?imdb=tt12735488"),
    ("VidLink HD (Interstellar)", "https://vidlink.pro/movie/tt0816692")
]

def test_embed_provider(test_id, name, url):
    start = time.time()
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            passed = resp.status == 200
            body = resp.read()
            details = f"HTTP {resp.status}, size: {len(body)} bytes"
            record(test_id, "Cloud Streaming", name, passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "Cloud Streaming", name, False, dur, str(e))

# ==================== 5. NATIVE MP4 STREAMING & RANGE REQUEST TESTS (91-97) ====================
REGIONAL_MP4_SAMPLES = [
    ("RRR Telugu HQ MP4", "https://archive.org/download/rrr-parrt-1-hand-brrrake/RRR%20Parrt%201%20HandBrrrake.ia.mp4"),
    ("Pushpa Telugu 720p MP4", "https://archive.org/download/pushpa-2021-telugu-720p-eagle-tv/Pushpa%20%282021%29%20Telugu%20720p%20%23EagleTV.mp4"),
    ("Geetha Govindam Telugu MP4", "https://archive.org/download/geetha-govindam-2018-telugu-org-x-264/Geetha%20Govindam%202018%20Telugu%20Org%20x264.mp4"),
    ("Arjun Reddy Telugu 720p MP4", "https://archive.org/download/arjun-reddy-2017-720p-telugu-hq-hdrip-hevc-dd-5.1-192kbps-1-gb-esub/Arjun%20Reddy%20%282017%29%20720p%20Telugu%20HQ%20HDRip%20-%20HEVC%20-%20%28DD5.1%20-%20192kbps%29%20-%201GB%20-%20ESub.mp4"),
    ("Salaar Telugu 720p MP4", "https://archive.org/download/salaar-part-1-telugu-drh-8i-2023-720p/Salaar.Part.1.Telugu.Drh8i.2023.720p.ia.mp4"),
    ("Baahubali Telugu MP4", "https://archive.org/download/bahubali-2015-1-cd-dvdscr-rip-x-264-mp-3-team-ddh-rg_202202/Bahubali%20%282015%29%20-%201CD%20-%20DVDSCR-Rip%20-%20x264%20-%20MP3%20-%20%5BTeam%20DDH~RG%5D.ia.mp4"),
    ("Vikram Telugu/Tamil MP4", "https://archive.org/download/vikram-2022-multi-auds-tel-tam-hin-eng-sub-720p-hdrip-x-264-esubs-mkvcinemas/Vikram%20%282022%29%20Multi%20Auds%5B%20Tel-Tam-Hin%20Eng%20Sub%5D%20720p%20HDRip%20x264%20ESubs%20-%20%5BMkvcinemas%5D.ia.mp4")
]

def test_range_streaming(test_id, name, url):
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={**HEADERS, "Range": "bytes=0-1024"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            passed = resp.status in (200, 206)
            content_type = resp.headers.get("Content-Type", "")
            content_range = resp.headers.get("Content-Range", "none")
            details = f"Status: {resp.status} | Type: {content_type} | Range: {content_range}"
            record(test_id, "Native Video Streams", name, passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "Native Video Streams", name, False, dur, str(e))

# ==================== 6. SECURITY & QUALITY VERIFICATION (98-100) ====================
def test_security_headers(test_id):
    start = time.time()
    try:
        req = urllib.request.Request(f"{BASE_URL}/", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            body = resp.read().decode('utf-8')
            has_no_referrer = 'referrerpolicy="no-referrer"' in body
            has_manifest = 'rel="manifest"' in body
            has_sw = 'navigator.serviceWorker' in body
            has_meta_viewport = 'name="viewport"' in body
            passed = has_no_referrer and has_manifest and has_sw and has_meta_viewport
            details = f"no-referrer: {has_no_referrer}, manifest: {has_manifest}, sw: {has_sw}, viewport: {has_meta_viewport}"
            record(test_id, "Security & PWA", "Production HTML Hardening Check", passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "Security & PWA", "Production HTML Hardening Check", False, dur, str(e))

def test_sw_cache_version(test_id):
    start = time.time()
    try:
        req = urllib.request.Request(f"{BASE_URL}/sw.js", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            body = resp.read().decode('utf-8')
            passed = "cinemahub-cache-v4" in body
            details = f"Found 'cinemahub-cache-v4': {passed}"
            record(test_id, "Security & PWA", "Service Worker Cache v4 Check", passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "Security & PWA", "Service Worker Cache v4 Check", False, dur, str(e))

def test_google_verification(test_id):
    start = time.time()
    try:
        req = urllib.request.Request(f"{BASE_URL}/googleeeae74686c9dc05e.html", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            dur = (time.time() - start) * 1000
            body = resp.read().decode('utf-8')
            passed = "google-site-verification" in body
            details = f"Google verification file present: {passed}"
            record(test_id, "SEO & Indexing", "Google Search Console Token", passed, dur, details)
    except Exception as e:
        dur = (time.time() - start) * 1000
        record(test_id, "SEO & Indexing", "Google Search Console Token", False, dur, str(e))

def main():
    print("=" * 80)
    print("STARTING 100-TESTER INDUSTRIAL QA SUITE ON https://cinemahub-vip.onrender.com")
    print("=" * 80)
    
    suite_start = time.time()

    # 1. Routes (1-10)
    test_static_route(1, "/", 200, "CinemaHub VIP")
    test_static_route(2, "/manifest.json", 200, "CinemaHub VIP")
    test_static_route(3, "/sw.js", 200, "cinemahub-cache-v4")
    test_static_route(4, "/googleeeae74686c9dc05e.html", 200, "google-site-verification")
    test_static_route(5, "/robots.txt", 200)
    test_static_route(6, "/sitemap.xml", 200)
    test_static_route(7, "/favicon.ico", 200)
    test_static_route(8, "/welcome_tour.mp3", 200)
    test_static_route(9, "/qrcode.min.js", 200)
    test_static_route(10, "/nonexistent_404_check", 404)

    # 2. APIs (11-25)
    test_get_api(11, "/api/ai_surprise", lambda d, s: (bool(d and d.get("title")), f"Surprise movie: {d.get('title') if d else ''}"))
    test_get_api(12, "/api/suggestions?q=arjun", lambda d, s: (bool(d and len(d.get("suggestions", [])) > 0), f"Found {len(d.get('suggestions', [])) if d else 0} suggestions"))
    test_get_api(13, "/api/suggestions?q=rrr", lambda d, s: (bool(d and len(d.get("suggestions", [])) > 0), f"Found {len(d.get('suggestions', [])) if d else 0} suggestions"))
    test_get_api(14, "/api/suggestions?q=incept", lambda d, s: (bool(d and len(d.get("suggestions", [])) > 0), f"Found {len(d.get('suggestions', [])) if d else 0} suggestions"))
    test_get_api(15, "/api/extract_stream?url=https%3A%2F%2Fvidlink.pro%2Fmovie%2Ftt7294534&quality=best", 
                 lambda d, s: (bool(d and d.get("stream_type") == "embed"), f"Extracted embed: {d.get('stream_url') if d else ''}"))
    test_get_api(16, "/api/extract_stream?url=https%3A%2F%2Farchive.org%2Fdownload%2Fpushpa-2021-telugu-720p-eagle-tv%2FPushpa%2520%25282021%2529%2520Telugu%2520720p%2520%2523EagleTV.mp4&quality=best", 
                 lambda d, s: (bool(d and d.get("stream_type") == "video"), f"Extracted direct video: {d.get('stream_url') if d else ''}"))
    test_post_api(17, "/api/mood_search", {"mood": "adrenaline action"}, 
                  lambda d, s: (bool(d and len(d.get("recommendations", [])) > 0), f"Action recommendations: {len(d.get('recommendations', [])) if d else 0}"))
    test_post_api(18, "/api/mood_search", {"mood": "telugu romance"}, 
                  lambda d, s: (bool(d and len(d.get("recommendations", [])) > 0), f"Telugu recommendations: {len(d.get('recommendations', [])) if d else 0}"))
    test_post_api(19, "/api/mood_search", {"mood": "mind-bending sci-fi"}, 
                  lambda d, s: (bool(d and len(d.get("recommendations", [])) > 0), f"Sci-Fi recommendations: {len(d.get('recommendations', [])) if d else 0}"))
    test_post_api(20, "/api/mood_search", {"mood": "cozy feel-good comedy"}, 
                  lambda d, s: (bool(d and len(d.get("recommendations", [])) > 0), f"Cozy recommendations: {len(d.get('recommendations', [])) if d else 0}"))
    test_post_api(21, "/api/sniff_url", {"url": "https://archive.org/download/pushpa-2021-telugu-720p-eagle-tv/Pushpa%20%282021%29%20Telugu%20720p%20%23EagleTV.mp4"},
                  lambda d, s: (bool(d and d.get("stream_url")), f"Sniffed URL: {d.get('title') if d else ''}"))
    test_post_api(22, "/api/search", {"query": "", "language": "English"},
                  lambda d, s: (s == 400, "Cleanly rejected empty query with HTTP 400"))
    test_post_api(23, "/api/search", {"query": "Arjun Reddy", "language": "Telugu"},
                  lambda d, s: (bool(d and len(d.get("results", [])) > 0 and any(r.get("imdb_id") == "tt7294534" or "Arjun Reddy" in r.get("title", "") for r in d["results"])), f"Found {len(d.get('results', [])) if d else 0} Arjun Reddy streams"))
    test_post_api(24, "/api/search", {"query": "RRR", "language": "Telugu"},
                  lambda d, s: (bool(d and len(d.get("results", [])) > 0 and any(r.get("imdb_id") == "tt8178634" or "RRR" in r.get("title", "") for r in d["results"])), f"Top result: {d['results'][0].get('title')[:30] if d and d.get('results') else ''}"))
    test_post_api(25, "/api/search", {"query": "Inception", "language": "English"},
                  lambda d, s: (bool(d and len(d.get("results", [])) > 0 and any(r.get("imdb_id") == "tt1375666" or "Inception" in r.get("title", "") for r in d["results"])), f"Found Inception results"))

    # 3. Search Matrix (26-75: 50 movies executed in parallel pool)
    print("\n>>> Launching Multi-Threaded Search Matrix (50 Movies Across 6 Languages)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        for idx, (movie, lang) in enumerate(MOVIE_TEST_SET):
            futures.append(executor.submit(test_search_movie, 26 + idx, movie, lang))
        concurrent.futures.wait(futures)

    # 4. Cloud Streaming Embeds (76-90)
    print("\n>>> Testing Cloud Embed Providers (VidLink, Smashy, VIP Cloud, Fast Mirror)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for idx, (name, url) in enumerate(EMBED_PROVIDERS):
            futures.append(executor.submit(test_embed_provider, 76 + idx, name, url))
        concurrent.futures.wait(futures)

    # 5. Native MP4 Range Streams (91-97)
    print("\n>>> Testing Native MP4 Video Streams & HTTP 206 Range Buffering...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for idx, (name, url) in enumerate(REGIONAL_MP4_SAMPLES):
            futures.append(executor.submit(test_range_streaming, 91 + idx, name, url))
        concurrent.futures.wait(futures)

    # 6. Security, PWA, SEO (98-100)
    print("\n>>> Verifying Security, PWA, and SEO Tokens...")
    test_security_headers(98)
    test_sw_cache_version(99)
    test_google_verification(100)

    # Summary
    suite_dur = round(time.time() - suite_start, 2)
    test_results.sort(key=lambda x: x["id"])
    passed_count = sum(1 for t in test_results if t["passed"])
    failed_count = sum(1 for t in test_results if not t["passed"])
    total_count = len(test_results)
    pass_rate = round((passed_count / total_count) * 100, 1)

    print("=" * 80)
    print(f"QA TEST RUN COMPLETED in {suite_dur}s")
    print(f"TOTAL TESTS: {total_count} | PASSED: {passed_count} | FAILED: {failed_count} | PASS RATE: {pass_rate}%")
    print("=" * 80)

    # Save detailed JSON report
    with open("qa_100_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "target": BASE_URL,
            "total": total_count,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate_pct": pass_rate,
            "duration_sec": suite_dur,
            "tests": test_results
        }, f, indent=2)

if __name__ == "__main__":
    main()
