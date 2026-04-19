#!/usr/bin/env python3
"""
Video Analysis Tool for Pine Script Development
Downloads YouTube videos, extracts transcripts, and analyzes trading content.

Methods (in order of preference):
1. YouTube's built-in captions (fastest, via youtube-transcript-api)
2. Whisper transcription of downloaded audio (slower, but works for any video)
"""

import os
import re
import json
import sys
import tempfile
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Force UTF-8 console output on Windows/legacy terminals to avoid
# UnicodeEncodeError when printing status symbols/emojis.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================================
# DEPENDENCY MANAGEMENT
# ============================================================================

def check_and_install_packages():
    """Check and install required packages"""
    packages = {
        'yt_dlp': 'yt-dlp',
        'youtube_transcript_api': 'youtube-transcript-api',
    }

    missing = []
    for module, pip_name in packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"📦 Installing missing packages: {', '.join(missing)}")
        import subprocess
        for pkg in missing:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
        print("✅ Packages installed")

check_and_install_packages()

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable
)
import yt_dlp

# ============================================================================
# CONFIGURATION
# ============================================================================

CACHE_DIR = Path("projects/analysis/.cache")
ANALYSIS_DIR = Path("projects/analysis")
STATUS_FILE = Path(".codex/.video_status")
LEGACY_STATUS_FILE_ASSISTANT = Path(".assistant/.video_status")
LEGACY_STATUS_FILE_CLAUDE = Path(".claude/.video_status")

def set_status(message: str):
    """Write status to file for statusline display"""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(message)
    except:
        pass  # Silently fail if can't write status

def clear_status():
    """Clear the status file"""
    try:
        if STATUS_FILE.exists():
            STATUS_FILE.unlink()
        if LEGACY_STATUS_FILE_ASSISTANT.exists():
            LEGACY_STATUS_FILE_ASSISTANT.unlink()
        if LEGACY_STATUS_FILE_CLAUDE.exists():
            LEGACY_STATUS_FILE_CLAUDE.unlink()
    except:
        pass

TRADING_KEYWORDS = {
    'indicators': [
        'rsi', 'relative strength', 'macd', 'moving average', 'ema', 'sma', 'wma',
        'bollinger bands', 'bollinger', 'stochastic', 'volume', 'atr', 'average true range',
        'adx', 'ichimoku', 'fibonacci', 'fib', 'pivot points', 'support', 'resistance',
        'vwap', 'momentum', 'cci', 'commodity channel', 'williams', 'obv', 'on balance',
        'keltner', 'donchian', 'parabolic sar', 'supertrend', 'heikin ashi'
    ],
    'patterns': [
        'breakout', 'trend', 'reversal', 'divergence', 'convergence', 'bullish divergence',
        'bearish divergence', 'hidden divergence', 'cross', 'crossover', 'crossunder',
        'golden cross', 'death cross', 'squeeze', 'flag', 'pennant', 'triangle',
        'head and shoulders', 'double top', 'double bottom', 'cup and handle',
        'wedge', 'channel', 'range', 'consolidation', 'pullback', 'retracement'
    ],
    'strategies': [
        'scalping', 'day trading', 'swing trading', 'position trading',
        'mean reversion', 'trend following', 'momentum trading', 'breakout trading',
        'range trading', 'grid trading', 'martingale', 'dca', 'dollar cost averaging',
        'smart money', 'order block', 'fair value gap', 'fvg', 'liquidity'
    ],
    'conditions': [
        'entry', 'exit', 'stop loss', 'take profit', 'risk management',
        'position sizing', 'trailing stop', 'break even', 'signal', 'alert',
        'confirmation', 'filter', 'trigger', 'buy signal', 'sell signal',
        'long', 'short', 'close position', 'partial profit'
    ],
    'timeframes': [
        '1 minute', '5 minute', '15 minute', '30 minute', '1 hour', '4 hour',
        'daily', 'weekly', 'monthly', 'multi timeframe', 'mtf', 'higher timeframe',
        'lower timeframe', 'htf', 'ltf', 'm1', 'm5', 'm15', 'm30', 'h1', 'h4', 'd1'
    ]
}

# ============================================================================
# VIDEO ANALYZER CLASS
# ============================================================================

class VideoAnalyzer:
    """Analyzes YouTube videos for trading strategy content"""

    def __init__(
        self,
        use_whisper: bool = False,
        whisper_model: str = "base",
        cookies_from_browser: str = "",
        cookies_file: str = "",
    ):
        self.use_whisper = use_whisper
        self.whisper_model = whisper_model
        self.cookies_from_browser = cookies_from_browser.strip()
        self.cookies_file = cookies_file.strip()
        self._whisper_model_loaded = None

        # Ensure directories exist
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    def _apply_cookie_options(self, ydl_opts: Dict) -> Dict:
        """Attach optional cookie settings to yt-dlp options."""
        if self.cookies_file:
            ydl_opts['cookiefile'] = self.cookies_file
        if self.cookies_from_browser:
            # Accept forms like "chrome" or "chrome:Default" or "firefox:profile"
            parts = [p for p in self.cookies_from_browser.split(':') if p]
            if len(parts) == 1:
                ydl_opts['cookiesfrombrowser'] = (parts[0],)
            elif len(parts) >= 2:
                ydl_opts['cookiesfrombrowser'] = tuple(parts)
        return ydl_opts

    def _apply_runtime_options(self, ydl_opts: Dict) -> Dict:
        """Attach yt-dlp JS runtime settings to reduce YouTube bot-check failures."""
        ydl_opts['js_runtimes'] = {"node": {}}
        ydl_opts['remote_components'] = {"ejs:github"}
        ydl_opts['cachedir'] = ".yt-dlp-cache"
        return ydl_opts

    def _is_cookie_copy_error(self, error: Exception) -> bool:
        """Detect yt-dlp browser cookie copy failures (common on locked Chrome DBs)."""
        text = str(error).lower()
        return (
            "could not copy chrome cookie database" in text
            or "cookiesfrombrowser" in text and "cookie database" in text
            or "could not copy" in text and "cookie" in text
            or "failed to decrypt with dpapi" in text
            or "dpapi" in text and "decrypt" in text
        )

    # ========================================================================
    # URL PARSING
    # ========================================================================

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from various URL formats"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)',
            r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)',
            r'(?:youtube\.com\/v\/)([\w-]+)',
            r'(?:youtube\.com\/shorts\/)([\w-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    # ========================================================================
    # METADATA FETCHING
    # ========================================================================

    def get_video_metadata(self, url: str) -> Dict:
        """Get video metadata using yt-dlp"""
        print("📋 Fetching video metadata...")
        set_status("🎬 Video: Fetching metadata...")

        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        base_opts = self._apply_runtime_options(base_opts)
        ydl_opts = self._apply_cookie_options(dict(base_opts))

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Unknown'),
                    'author': info.get('uploader', 'Unknown'),
                    'channel_url': info.get('uploader_url', ''),
                    'duration': info.get('duration', 0),
                    'duration_string': info.get('duration_string', 'Unknown'),
                    'description': (info.get('description', '') or '')[:1000],
                    'upload_date': info.get('upload_date', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                }
        except Exception as e:
            # Retry without browser cookies if Chrome cookie DB is locked/unreadable.
            if self._is_cookie_copy_error(e) and (self.cookies_from_browser or self.cookies_file):
                print("⚠️  Cookie access failed. Retrying metadata without browser cookies...")
                try:
                    with yt_dlp.YoutubeDL(base_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        return {
                            'title': info.get('title', 'Unknown'),
                            'author': info.get('uploader', 'Unknown'),
                            'channel_url': info.get('uploader_url', ''),
                            'duration': info.get('duration', 0),
                            'duration_string': info.get('duration_string', 'Unknown'),
                            'description': (info.get('description', '') or '')[:1000],
                            'upload_date': info.get('upload_date', 'Unknown'),
                            'view_count': info.get('view_count', 0),
                            'like_count': info.get('like_count', 0),
                            'thumbnail': info.get('thumbnail', ''),
                        }
                except Exception as retry_err:
                    print(f"⚠️  Could not fetch metadata: {retry_err}")
                    return {'title': 'Unknown', 'author': 'Unknown', 'error': str(retry_err)}

            print(f"⚠️  Could not fetch metadata: {e}")
            return {'title': 'Unknown', 'author': 'Unknown', 'error': str(e)}

    # ========================================================================
    # TRANSCRIPT EXTRACTION
    # ========================================================================

    def _normalize_text(self, text: str) -> str:
        """Normalize transcript text for downstream parsing."""
        text = re.sub(r'\[.*?\]', '', text)  # Remove [Music], [Applause], etc.
        text = re.sub(r'♪.*?♪', '', text)  # Remove ♪ music lyrics markers ♪
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _sentences_from_transcript_segments(self, transcript_data) -> List[str]:
        """Build sentence-like units from transcript segments, even with poor punctuation."""
        sentences: List[str] = []
        for entry in transcript_data:
            if hasattr(entry, 'text'):
                segment = entry.text
            elif isinstance(entry, dict):
                segment = entry.get('text', '')
            else:
                segment = str(entry)

            segment = self._normalize_text(segment)
            if not segment:
                continue

            # If segment has no terminal punctuation, add a period to improve splitting quality.
            if segment[-1] not in ".!?":
                segment = segment + "."
            sentences.append(segment)

        return sentences

    def get_transcript_from_youtube(self, video_id: str) -> Tuple[Optional[str], str]:
        """Try to get transcript from YouTube's captions (fastest method)"""
        print("📝 Attempting to fetch YouTube captions...")
        set_status("🎬 Video: Fetching captions...")

        try:
            # Create API instance (required in newer versions of youtube-transcript-api)
            api = YouTubeTranscriptApi()

            # Try to get transcript, preferring manual captions over auto-generated
            transcript_list = api.list(video_id)

            # First try to get manually created English transcript
            transcript = None
            source = None

            # Look for manual English transcript first
            for t in transcript_list:
                if t.language_code in ['en', 'en-US', 'en-GB'] and not t.is_generated:
                    transcript = t
                    source = "manual_captions"
                    print("✅ Found manual English captions")
                    break

            # Fall back to auto-generated English
            if transcript is None:
                for t in transcript_list:
                    if t.language_code in ['en', 'en-US', 'en-GB'] and t.is_generated:
                        transcript = t
                        source = "auto_captions"
                        print("✅ Found auto-generated English captions")
                        break

            # Try any English variant
            if transcript is None:
                try:
                    transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                    source = "english_captions"
                    print("✅ Found English captions")
                except:
                    return None, "no_captions"

            # Fetch the actual transcript
            transcript_data = transcript.fetch()

            # Build transcript with sentence boundaries preserved for better rule extraction.
            sentence_segments = self._sentences_from_transcript_segments(transcript_data)
            full_text = " ".join(sentence_segments)

            return full_text, source

        except TranscriptsDisabled:
            print("⚠️  Transcripts are disabled for this video")
            return None, "disabled"
        except NoTranscriptFound:
            print("⚠️  No transcript found")
            return None, "not_found"
        except VideoUnavailable:
            print("⚠️  Video is unavailable")
            return None, "unavailable"
        except Exception as e:
            print(f"⚠️  Error fetching transcript: {e}")
            return None, f"error: {str(e)}"

    def get_transcript_from_whisper(self, url: str) -> Tuple[Optional[str], str]:
        """Download audio and transcribe with Whisper (slower but more reliable)"""
        print("🎙️ Downloading audio and transcribing with Whisper...")
        print(f"   (Using '{self.whisper_model}' model - this may take a few minutes)")
        set_status("🎬 Video: Downloading audio...")

        try:
            # Lazy load whisper
            if self._whisper_model_loaded is None:
                try:
                    import whisper
                    print(f"   Loading Whisper model...")
                    self._whisper_model_loaded = whisper.load_model(self.whisper_model)
                except ImportError:
                    print("⚠️  Whisper not installed. Installing...")
                    import subprocess
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "openai-whisper"])
                    import whisper
                    self._whisper_model_loaded = whisper.load_model(self.whisper_model)

            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = os.path.join(temp_dir, 'audio.mp3')
                outtmpl = os.path.join(temp_dir, 'audio.%(ext)s')

                print("   📥 Downloading audio...")
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': outtmpl,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'quiet': True,
                    'no_warnings': True,
                }
                ydl_opts = self._apply_runtime_options(ydl_opts)
                ydl_opts = self._apply_cookie_options(ydl_opts)
                retry_without_cookies = False

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except Exception as e:
                    if self._is_cookie_copy_error(e) and (self.cookies_from_browser or self.cookies_file):
                        print("   ⚠️  Cookie access failed, retrying without browser cookies...")
                        retry_without_cookies = True
                        ydl_opts_no_cookies = {
                            'format': 'bestaudio/best',
                            'outtmpl': outtmpl,
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'quiet': True,
                            'no_warnings': True,
                        }
                        ydl_opts_no_cookies = self._apply_runtime_options(ydl_opts_no_cookies)
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts_no_cookies) as ydl:
                                ydl.download([url])
                            e = None
                        except Exception as retry_e:
                            e = retry_e

                    # FFmpeg post-processing can fail on some Windows setups.
                    # Fallback to a direct audio download and let Whisper decode it.
                    if e is not None:
                        print(f"   ⚠️  FFmpeg conversion failed, retrying direct audio download: {e}")
                        ydl_opts_fallback = {
                            'format': 'bestaudio/best',
                            'outtmpl': outtmpl,
                            'quiet': True,
                            'no_warnings': True,
                        }
                        ydl_opts_fallback = self._apply_runtime_options(ydl_opts_fallback)
                        if not retry_without_cookies:
                            ydl_opts_fallback = self._apply_cookie_options(ydl_opts_fallback)
                        with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                            ydl.download([url])

                # Find the downloaded file
                for f in os.listdir(temp_dir):
                    if f.lower().endswith(('.mp3', '.m4a', '.webm', '.opus', '.wav', '.aac', '.flac', '.mp4')):
                        audio_path = os.path.join(temp_dir, f)
                        break

                if not os.path.exists(audio_path):
                    return None, "download_failed"

                print("   🔊 Transcribing audio...")
                set_status("🎬 Video: Transcribing with Whisper...")
                result = self._whisper_model_loaded.transcribe(audio_path)

                return self._normalize_text(result["text"]), "whisper"

        except Exception as e:
            print(f"⚠️  Whisper transcription failed: {e}")
            return None, f"whisper_error: {str(e)}"

    def get_transcript(self, url: str, video_id: str) -> Tuple[Optional[str], str]:
        """Get transcript using best available method"""
        # Check cache first
        cache_file = CACHE_DIR / f"{video_id}_transcript.json"
        if cache_file.exists():
            print("📦 Using cached transcript")
            with open(cache_file, 'r') as f:
                cached = json.load(f)
                return cached['text'], cached['source'] + "_cached"

        # In forced Whisper mode, try Whisper first, then fall back to captions.
        if self.use_whisper:
            transcript, source = self.get_transcript_from_whisper(url)
            if transcript:
                with open(cache_file, 'w') as f:
                    json.dump({'text': transcript, 'source': source}, f)
                return transcript, source

            print("🔄 Whisper failed, trying YouTube captions as fallback...")
            transcript, source = self.get_transcript_from_youtube(video_id)
            if transcript:
                with open(cache_file, 'w') as f:
                    json.dump({'text': transcript, 'source': source}, f)
                return transcript, source

            return transcript, source

        # Try YouTube captions first (much faster)
        if not self.use_whisper:
            transcript, source = self.get_transcript_from_youtube(video_id)
            if transcript:
                # Cache it
                with open(cache_file, 'w') as f:
                    json.dump({'text': transcript, 'source': source}, f)
                return transcript, source

        # Fall back to Whisper
        print("🔄 Falling back to Whisper transcription...")
        transcript, source = self.get_transcript_from_whisper(url)
        if transcript:
            # Cache it
            with open(cache_file, 'w') as f:
                json.dump({'text': transcript, 'source': source}, f)

        return transcript, source

    # ========================================================================
    # CONTENT ANALYSIS
    # ========================================================================

    def extract_key_concepts(self, text: str) -> Dict:
        """Extract trading concepts from transcript text"""
        text_lower = text.lower()
        found_concepts = {category: [] for category in TRADING_KEYWORDS}
        found_concepts['specific_values'] = []

        # Find mentioned concepts
        for category, keywords in TRADING_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    # Count occurrences for relevance ranking
                    count = text_lower.count(keyword)
                    found_concepts[category].append({
                        'term': keyword,
                        'count': count
                    })

        # Sort by frequency and deduplicate
        for category in TRADING_KEYWORDS:
            seen = set()
            unique = []
            for item in sorted(found_concepts[category], key=lambda x: -x['count']):
                if item['term'] not in seen:
                    seen.add(item['term'])
                    unique.append(item['term'])
            found_concepts[category] = unique[:10]  # Top 10 per category

        # Extract specific numeric values
        patterns = [
            (r'(\d+)\s*(?:period|length|bar|candle)s?', 'periods'),
            (r'(\d+\.?\d*)\s*(?:%|percent)', 'percentages'),
            (r'(\d+)\s*(?:pip|point|tick)s?', 'pips'),
            (r'(?:level|zone|area|price)\s*(?:of|at|around)?\s*\$?(\d+\.?\d*)', 'levels'),
            (r'(\d+)\s*(?:ema|sma|ma)\b', 'ma_lengths'),
            (r'(?:rsi|stochastic)\s*(?:of|at|above|below)?\s*(\d+)', 'oscillator_levels'),
        ]

        for pattern, value_type in patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                unique_values = list(set(matches))[:5]
                if unique_values:
                    found_concepts['specific_values'].append({
                        'type': value_type,
                        'values': unique_values
                    })

        return found_concepts

    def _match_rule_signal(self, sentence_lower: str, terms: List[str]) -> bool:
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", sentence_lower):
                return True
        return False

    def identify_strategy_components(self, text: str) -> Dict:
        """Identify specific strategy components from transcript"""
        components = {
            'entry_conditions': [],
            'exit_conditions': [],
            'risk_management': [],
            'indicators_mentioned': [],
            'timeframes': [],
            'market_conditions': [],
            'key_rules': []
        }

        # Split into sentences
        # Use punctuation split first, then fall back to transcript fragment split.
        punctuation_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if len(punctuation_sentences) < 10:
            punctuation_sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
        sentences = punctuation_sentences

        entry_keywords = ['enter', 'buy', 'long', 'entry', 'go long', 'open', 'get in']
        exit_keywords = ['exit', 'sell', 'close', 'take profit', 'stop loss', 'get out', 'close position']
        risk_keywords = ['risk', 'position size', 'money management', 'drawdown', 'stop loss', 'trailing stop', 'break even']
        condition_phrases = ['when', 'if', 'once', 'only if', 'as soon as', 'provided that', 'after']
        noisy_prefixes = ['welcome', 'subscribe', 'like and subscribe', 'disclaimer', 'not financial advice']

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 12:
                continue

            sentence_lower = sentence.lower()
            if any(prefix in sentence_lower for prefix in noisy_prefixes):
                continue
            if len(sentence.split()) > 45:
                # Long run-on narration is usually poor signal for deterministic trading rules.
                continue

            # Entry conditions
            if self._match_rule_signal(sentence_lower, entry_keywords):
                if any(phrase in sentence_lower for phrase in condition_phrases):
                    components['entry_conditions'].append(sentence)

            # Exit conditions
            if self._match_rule_signal(sentence_lower, exit_keywords):
                if any(phrase in sentence_lower for phrase in condition_phrases + ['at']):
                    components['exit_conditions'].append(sentence)

            # Risk management
            if self._match_rule_signal(sentence_lower, risk_keywords):
                components['risk_management'].append(sentence)

            # Key rules (sentences with "always", "never", "must", "important")
            if any(word in sentence_lower for word in ['always', 'never', 'must', 'important', 'rule', 'key']):
                components['key_rules'].append(sentence)

        # Limit to most relevant entries
        for key in components:
            if isinstance(components[key], list):
                components[key] = components[key][:5]

        # Deduplicate while preserving order.
        for key in ['entry_conditions', 'exit_conditions', 'risk_management', 'key_rules']:
            deduped = []
            seen = set()
            for item in components[key]:
                normalized = item.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(item)
            components[key] = deduped[:5]

        return components

    # ========================================================================
    # SPECIFICATION GENERATION
    # ========================================================================

    def generate_pine_script_spec(self, concepts: Dict, components: Dict, metadata: Dict, transcript_source: str) -> Dict:
        """Generate Pine Script specification from analysis"""

        # Determine script type
        has_entry_exit = bool(components.get('entry_conditions') or components.get('exit_conditions'))
        script_type = 'strategy' if has_entry_exit else 'indicator'

        # Calculate complexity
        complexity = self._calculate_complexity(concepts, components)

        spec = {
            'video_info': {
                'title': metadata.get('title', 'Unknown'),
                'author': metadata.get('author', 'Unknown'),
                'duration': metadata.get('duration_string', 'Unknown'),
                'url': metadata.get('url', ''),
                'transcript_source': transcript_source,
                'analyzed_at': datetime.now().isoformat()
            },
            'script_type': script_type,
            'complexity_score': complexity,
            'main_indicators': concepts.get('indicators', [])[:5],
            'patterns': concepts.get('patterns', [])[:5],
            'strategy_style': concepts.get('strategies', ['custom'])[0] if concepts.get('strategies') else 'custom',
            'timeframes': concepts.get('timeframes', [])[:3],
            'implementation': {
                'entry_logic': components.get('entry_conditions', []),
                'exit_logic': components.get('exit_conditions', []),
                'risk_rules': components.get('risk_management', []),
                'key_rules': components.get('key_rules', []),
            },
            'parameters': concepts.get('specific_values', []),
            'feasibility': self._assess_feasibility(concepts, components),
            'suggested_features': self._suggest_features(concepts, components, script_type)
        }

        return spec

    def _calculate_complexity(self, concepts: Dict, components: Dict) -> int:
        """Calculate complexity score 1-10"""
        score = 1
        score += min(len(concepts.get('indicators', [])), 3)
        score += min(len(concepts.get('patterns', [])), 2)
        score += 1 if components.get('entry_conditions') else 0
        score += 1 if components.get('exit_conditions') else 0
        score += 1 if components.get('risk_management') else 0
        score += 1 if len(concepts.get('timeframes', [])) > 1 else 0
        return min(score, 10)

    def _assess_feasibility(self, concepts: Dict, components: Dict) -> Dict:
        """Assess Pine Script implementation feasibility"""
        issues = []

        # Check for potentially problematic concepts
        problematic = ['machine learning', 'neural network', 'ai', 'sentiment', 'news']
        for term in concepts.get('strategies', []) + concepts.get('indicators', []):
            if any(p in term.lower() for p in problematic):
                issues.append(f"'{term}' may require external data or complex implementation")

        if len(concepts.get('indicators', [])) > 5:
            issues.append("Many indicators - may need to optimize for performance")

        return {
            'overall': 'full' if not issues else 'partial',
            'issues': issues,
            'pine_script_compatible': len(issues) == 0
        }

    def _suggest_features(self, concepts: Dict, components: Dict, script_type: str) -> List[str]:
        """Suggest features to implement"""
        suggestions = []

        if script_type == 'strategy':
            if not components.get('risk_management'):
                suggestions.append("Add position sizing and risk management")
            suggestions.append("Include backtesting performance table")
            suggestions.append("Add alert conditions for signals")
        else:
            suggestions.append("Add visual signal markers")
            suggestions.append("Include info panel with current values")

        if concepts.get('timeframes') and len(concepts.get('timeframes', [])) > 1:
            suggestions.append("Implement multi-timeframe analysis")

        suggestions.append("Add input groups with tooltips")
        suggestions.append("Include debug mode toggle")

        return suggestions[:5]

    # ========================================================================
    # OUTPUT GENERATION
    # ========================================================================

    def create_summary(self, spec: Dict) -> str:
        """Create user-friendly summary"""
        indicators = ', '.join(spec['main_indicators'][:5]) if spec['main_indicators'] else 'None detected'
        patterns = ', '.join(spec['patterns'][:3]) if spec['patterns'] else 'None detected'
        timeframes = ', '.join(spec['timeframes'][:3]) if spec['timeframes'] else 'Not specified'

        entry_count = len(spec['implementation']['entry_logic'])
        exit_count = len(spec['implementation']['exit_logic'])
        risk_count = len(spec['implementation']['risk_rules'])

        summary = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         📹 VIDEO ANALYSIS COMPLETE                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

📺 Source: {spec['video_info']['title'][:60]}
👤 Author: {spec['video_info']['author']}
⏱️  Duration: {spec['video_info']['duration']}
📝 Transcript: {spec['video_info']['transcript_source']}

┌──────────────────────────────────────────────────────────────────────────────┐
│ ANALYSIS RESULTS                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

  📊 Script Type:     {spec['script_type'].upper()}
  ⚡ Complexity:      {spec['complexity_score']}/10
  🎯 Strategy Style:  {spec['strategy_style']}
  ✅ Feasibility:     {spec['feasibility']['overall'].upper()}

┌──────────────────────────────────────────────────────────────────────────────┐
│ DETECTED COMPONENTS                                                           │
└──────────────────────────────────────────────────────────────────────────────┘

  📈 Indicators:  {indicators}
  📐 Patterns:    {patterns}
  ⏰ Timeframes:  {timeframes}

┌──────────────────────────────────────────────────────────────────────────────┐
│ TRADING LOGIC                                                                 │
└──────────────────────────────────────────────────────────────────────────────┘

  🟢 Entry Conditions:  {entry_count} identified
  🔴 Exit Conditions:   {exit_count} identified
  🛡️  Risk Rules:        {risk_count} identified
"""

        # Add entry conditions detail
        if spec['implementation']['entry_logic']:
            summary += "\n  Entry Logic Found:\n"
            for i, condition in enumerate(spec['implementation']['entry_logic'][:3], 1):
                summary += f"    {i}. {condition[:80]}...\n" if len(condition) > 80 else f"    {i}. {condition}\n"

        # Add exit conditions detail
        if spec['implementation']['exit_logic']:
            summary += "\n  Exit Logic Found:\n"
            for i, condition in enumerate(spec['implementation']['exit_logic'][:3], 1):
                summary += f"    {i}. {condition[:80]}...\n" if len(condition) > 80 else f"    {i}. {condition}\n"

        # Add suggested features
        if spec['suggested_features']:
            summary += f"""
┌──────────────────────────────────────────────────────────────────────────────┐
│ SUGGESTED FEATURES                                                            │
└──────────────────────────────────────────────────────────────────────────────┘

"""
            for feature in spec['suggested_features']:
                summary += f"  • {feature}\n"

        # Add feasibility issues if any
        if spec['feasibility']['issues']:
            summary += f"""
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⚠️  IMPLEMENTATION NOTES                                                       │
└──────────────────────────────────────────────────────────────────────────────┘

"""
            for issue in spec['feasibility']['issues']:
                summary += f"  • {issue}\n"

        summary += """
╔══════════════════════════════════════════════════════════════════════════════╗
║  Ready to implement! Type 'yes' to proceed, or describe any adjustments.     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

        return summary

    def save_analysis(self, analysis: Dict, video_id: str) -> str:
        """Save analysis to JSON file"""
        filename = f"analysis_{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = ANALYSIS_DIR / filename

        with open(filepath, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)

        return str(filepath)

    # ========================================================================
    # MAIN ANALYSIS FUNCTION
    # ========================================================================

    def analyze(self, url: str) -> Dict:
        """Main analysis function"""
        print("\n🎬 Starting Video Analysis...")
        print("=" * 60)
        set_status("🎬 Video: Starting analysis...")

        # Extract video ID
        video_id = self.extract_video_id(url)
        if not video_id:
            return {'success': False, 'error': 'Invalid YouTube URL'}

        print(f"🔗 Video ID: {video_id}")

        # Get metadata
        metadata = self.get_video_metadata(url)
        metadata['url'] = url

        if 'error' in metadata and metadata.get('title') == 'Unknown':
            print("⚠️  Metadata access failed. Continuing with transcript-only analysis...")

        print(f"📺 Title: {metadata['title'][:50]}...")

        # Get transcript
        transcript, source = self.get_transcript(url, video_id)

        if not transcript:
            return {
                'success': False,
                'error': f'Could not get transcript ({source}). Try with --whisper flag.',
                'metadata': metadata
            }

        print(f"✅ Transcript obtained: {len(transcript)} characters ({source})")

        # Analyze content
        print("🔍 Analyzing trading content...")
        set_status("🎬 Video: Analyzing trading concepts...")
        concepts = self.extract_key_concepts(transcript)
        components = self.identify_strategy_components(transcript)

        # Generate specification
        spec = self.generate_pine_script_spec(concepts, components, metadata, source)

        # Create summary
        summary = self.create_summary(spec)

        # Compile results
        result = {
            'success': True,
            'video_id': video_id,
            'summary': summary,
            'spec': spec,
            'concepts': concepts,
            'components': components,
            'transcript_length': len(transcript),
            'transcript_preview': transcript[:500] + '...' if len(transcript) > 500 else transcript
        }

        # Save analysis
        filepath = self.save_analysis(result, video_id)
        result['saved_to'] = filepath

        # Clear status - analysis complete
        set_status("✅ Video analysis complete!")

        return result


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Analyze YouTube videos for Pine Script development',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python video-analyzer.py https://youtube.com/watch?v=ABC123
  python video-analyzer.py https://youtu.be/ABC123 --whisper
  python video-analyzer.py "https://youtube.com/watch?v=ABC123" --whisper --model medium
        """
    )

    parser.add_argument('url', help='YouTube video URL')
    parser.add_argument('--whisper', action='store_true',
                        help='Force Whisper transcription (slower but more accurate)')
    parser.add_argument('--model', default='base',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper model size (default: base)')
    parser.add_argument('--json', action='store_true',
                        help='Output raw JSON instead of formatted summary')
    parser.add_argument('--cookies-from-browser', default='',
                        help='Pass browser cookies to yt-dlp (e.g. chrome or chrome:Default).')
    parser.add_argument('--cookies', default='',
                        help='Path to cookies.txt file for yt-dlp.')

    args = parser.parse_args()

    analyzer = VideoAnalyzer(
        use_whisper=args.whisper,
        whisper_model=args.model,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
    )
    result = analyzer.analyze(args.url)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        clear_status()
    elif result['success']:
        print(result['summary'])
        print(f"\n📁 Full analysis saved to: {result['saved_to']}")
        clear_status()
    else:
        print(f"\n❌ Error: {result.get('error', 'Unknown error')}")
        clear_status()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_status()
        print("\n⚠️ Analysis cancelled by user")
        sys.exit(1)
    except Exception as e:
        clear_status()
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
