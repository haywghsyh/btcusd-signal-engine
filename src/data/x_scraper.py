"""
X (Twitter) Scraper - Collect BTC-related posts without API.

Uses multiple strategies:
1. Nitter instances (open-source X frontend) for RSS/HTML scraping
2. Direct web scraping as fallback

Collects sentiment data from crypto influencers for AI analysis.
"""
import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Nitter instances (public, may change over time)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.unixfox.eu",
]

# Influential BTC/crypto accounts to monitor
DEFAULT_ACCOUNTS = [
    "whale_alert",
    "BitcoinMagazine",
    "DocumentingBTC",
    "WatcherGuru",
    "CryptoQuant_com",
    "glaboratorynet",  # Glassnode
    "100trillionUSD",  # PlanB
    "wolonom",  # Willy Woo
    "APompliano",
    "michael_saylor",
]

# BTC-related keywords for search
BTC_KEYWORDS = [
    "bitcoin", "btc", "btcusd", "#bitcoin", "#btc",
    "BTC whale", "bitcoin whale", "bitcoin liquidation",
    "bitcoin pump", "bitcoin dump", "bitcoin crash",
    "bitcoin rally", "bitcoin breakout", "bitcoin support",
    "bitcoin resistance",
]

# Sentiment keywords
BULLISH_KEYWORDS = [
    "bullish", "pump", "moon", "rally", "breakout", "buy",
    "accumulate", "higher", "support", "bounce", "green",
    "long", "ath", "new high", "bull run", "uptick",
    "強気", "上昇", "買い",
]

BEARISH_KEYWORDS = [
    "bearish", "dump", "crash", "drop", "breakdown", "sell",
    "liquidation", "lower", "resistance", "red", "short",
    "capitulation", "fear", "panic", "correction",
    "弱気", "下落", "売り",
]


@dataclass
class XPost:
    """Represents a single X post."""
    username: str
    text: str
    timestamp: Optional[datetime] = None
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    url: str = ""
    sentiment: str = "neutral"  # bullish, bearish, neutral
    sentiment_score: float = 0.0  # -1.0 to 1.0

    @property
    def post_id(self) -> str:
        """Generate a unique ID for dedup."""
        content = f"{self.username}:{self.text[:100]}"
        return hashlib.md5(content.encode()).hexdigest()

    @property
    def engagement(self) -> int:
        return self.likes + self.retweets + self.replies


@dataclass
class XSentimentSummary:
    """Aggregated sentiment from X posts."""
    total_posts: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    avg_sentiment_score: float = 0.0
    top_posts: List[XPost] = field(default_factory=list)
    collection_time: Optional[datetime] = None
    whale_alerts: List[str] = field(default_factory=list)

    @property
    def sentiment_label(self) -> str:
        if self.total_posts == 0:
            return "データなし"
        if self.avg_sentiment_score > 0.15:
            return "強気（Bullish）"
        elif self.avg_sentiment_score < -0.15:
            return "弱気（Bearish）"
        return "中立（Neutral）"

    @property
    def bullish_ratio(self) -> float:
        if self.total_posts == 0:
            return 0.0
        return self.bullish_count / self.total_posts

    @property
    def bearish_ratio(self) -> float:
        if self.total_posts == 0:
            return 0.0
        return self.bearish_count / self.total_posts

    def to_ai_summary(self) -> str:
        """Format for AI analysis prompt."""
        if self.total_posts == 0:
            return "X（Twitter）データ: 取得なし"

        lines = [
            f"X（Twitter）センチメント分析（直近投稿 {self.total_posts}件）:",
            f"  全体センチメント: {self.sentiment_label}",
            f"  スコア: {self.avg_sentiment_score:+.2f}（-1.0=極度弱気 ～ +1.0=極度強気）",
            f"  強気: {self.bullish_count}件 / 弱気: {self.bearish_count}件 / 中立: {self.neutral_count}件",
        ]

        if self.whale_alerts:
            lines.append(f"  クジラアラート: {len(self.whale_alerts)}件")
            for alert in self.whale_alerts[:3]:
                lines.append(f"    - {alert[:120]}")

        if self.top_posts:
            lines.append("  注目投稿:")
            for post in self.top_posts[:5]:
                engagement_str = f"(♥{post.likes} RT{post.retweets})"
                lines.append(
                    f"    @{post.username} {engagement_str}: "
                    f"{post.text[:100]}..."
                )

        return "\n".join(lines)


class XScraper:
    """Scrape X (Twitter) for BTC sentiment without API access."""

    def __init__(
        self,
        accounts: Optional[List[str]] = None,
        nitter_instances: Optional[List[str]] = None,
        cache_ttl_seconds: int = 300,
        request_timeout: int = 15,
        max_posts_per_account: int = 10,
    ):
        self.accounts = accounts or DEFAULT_ACCOUNTS
        self.nitter_instances = nitter_instances or NITTER_INSTANCES.copy()
        self.cache_ttl = cache_ttl_seconds
        self.timeout = request_timeout
        self.max_posts_per_account = max_posts_per_account

        self._cache: Optional[XSentimentSummary] = None
        self._cache_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self._working_instance: Optional[str] = None

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def get_sentiment(self, force_refresh: bool = False) -> XSentimentSummary:
        """
        Get aggregated BTC sentiment from X.
        Uses cache to avoid hammering sources.
        """
        with self._lock:
            if not force_refresh and self._is_cache_valid():
                return self._cache

        try:
            posts = self._collect_posts()
            summary = self._analyze_sentiment(posts)
            summary.collection_time = datetime.now(timezone.utc)

            with self._lock:
                self._cache = summary
                self._cache_time = datetime.now(timezone.utc)

            logger.info(
                f"X sentiment collected: {summary.total_posts} posts, "
                f"score={summary.avg_sentiment_score:+.2f} ({summary.sentiment_label})"
            )
            return summary

        except Exception as e:
            logger.error(f"X sentiment collection failed: {e}")
            with self._lock:
                if self._cache is not None:
                    return self._cache
            return XSentimentSummary()

    def _is_cache_valid(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return elapsed < self.cache_ttl

    def _collect_posts(self) -> List[XPost]:
        """Collect posts from all monitored accounts."""
        all_posts = []

        # Strategy 1: Nitter scraping (account timelines)
        nitter_posts = self._scrape_nitter_accounts()
        all_posts.extend(nitter_posts)

        # Strategy 2: Nitter search for BTC keywords
        if len(all_posts) < 10:
            search_posts = self._scrape_nitter_search()
            all_posts.extend(search_posts)

        # Deduplicate by post_id
        seen = set()
        unique_posts = []
        for post in all_posts:
            if post.post_id not in seen:
                seen.add(post.post_id)
                unique_posts.append(post)

        logger.info(f"Collected {len(unique_posts)} unique posts from X")
        return unique_posts

    def _find_working_nitter(self) -> Optional[str]:
        """Find a working Nitter instance."""
        if self._working_instance:
            try:
                resp = self._session.get(
                    self._working_instance,
                    timeout=5,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    return self._working_instance
            except Exception:
                self._working_instance = None

        for instance in self.nitter_instances:
            try:
                resp = self._session.get(
                    f"{instance}/BitcoinMagazine",
                    timeout=8,
                    allow_redirects=True,
                )
                if resp.status_code == 200 and len(resp.text) > 500:
                    self._working_instance = instance
                    logger.info(f"Using Nitter instance: {instance}")
                    return instance
            except Exception:
                continue

        logger.warning("No working Nitter instance found")
        return None

    def _scrape_nitter_accounts(self) -> List[XPost]:
        """Scrape account timelines via Nitter."""
        instance = self._find_working_nitter()
        if not instance:
            return []

        posts = []
        for account in self.accounts:
            try:
                account_posts = self._scrape_nitter_timeline(instance, account)
                posts.extend(account_posts)
                # Be polite - small delay between requests
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"Failed to scrape @{account}: {e}")
                continue

        return posts

    def _scrape_nitter_timeline(self, instance: str, username: str) -> List[XPost]:
        """Scrape a single account's timeline from Nitter."""
        url = f"{instance}/{username}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            posts = []

            # Nitter uses .timeline-item for each tweet
            tweet_elements = soup.select(".timeline-item")
            if not tweet_elements:
                # Alternative selector
                tweet_elements = soup.select(".tweet-body")

            for tweet in tweet_elements[: self.max_posts_per_account]:
                post = self._parse_nitter_tweet(tweet, username, instance)
                if post and self._is_btc_related(post.text):
                    posts.append(post)

            return posts

        except Exception as e:
            logger.debug(f"Nitter timeline error for @{username}: {e}")
            return []

    def _parse_nitter_tweet(
        self, element, default_username: str, instance: str
    ) -> Optional[XPost]:
        """Parse a single tweet element from Nitter HTML."""
        try:
            # Extract text
            text_el = element.select_one(".tweet-content, .media-body")
            if not text_el:
                return None
            text = text_el.get_text(strip=True)
            if not text or len(text) < 10:
                return None

            # Extract username
            user_el = element.select_one(".username, .tweet-header a")
            username = default_username
            if user_el:
                username = user_el.get_text(strip=True).lstrip("@")

            # Extract engagement stats
            likes = self._extract_stat(element, ".icon-heart", ".tweet-stat")
            retweets = self._extract_stat(element, ".icon-retweet", ".tweet-stat")
            replies = self._extract_stat(element, ".icon-comment", ".tweet-stat")

            # Extract timestamp
            time_el = element.select_one(".tweet-date a, time")
            timestamp = None
            if time_el:
                time_attr = time_el.get("title") or time_el.get("datetime")
                if time_attr:
                    timestamp = self._parse_timestamp(time_attr)

            # Extract URL
            link_el = element.select_one(".tweet-link, .tweet-date a")
            url = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                if href.startswith("/"):
                    url = f"https://x.com{href}"
                else:
                    url = href

            return XPost(
                username=username,
                text=text,
                timestamp=timestamp,
                likes=likes,
                retweets=retweets,
                replies=replies,
                url=url,
            )

        except Exception as e:
            logger.debug(f"Tweet parse error: {e}")
            return None

    def _extract_stat(self, element, icon_class: str, stat_class: str) -> int:
        """Extract engagement stat from Nitter HTML."""
        try:
            stats = element.select(stat_class)
            for stat in stats:
                icon = stat.select_one(icon_class)
                if icon:
                    num_el = stat.select_one(".tweet-stat-num, .icon-val")
                    if num_el:
                        return self._parse_number(num_el.get_text(strip=True))
            return 0
        except Exception:
            return 0

    def _scrape_nitter_search(self) -> List[XPost]:
        """Search for BTC-related posts via Nitter search."""
        instance = self._find_working_nitter()
        if not instance:
            return []

        posts = []
        search_terms = ["bitcoin", "BTC whale", "bitcoin liquidation"]

        for term in search_terms:
            try:
                encoded = quote_plus(term)
                url = f"{instance}/search?f=tweets&q={encoded}"
                resp = self._session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                tweet_elements = soup.select(".timeline-item")

                for tweet in tweet_elements[:5]:
                    post = self._parse_nitter_tweet(tweet, "unknown", instance)
                    if post:
                        posts.append(post)

                time.sleep(0.5)

            except Exception as e:
                logger.debug(f"Nitter search error for '{term}': {e}")
                continue

        return posts

    def _analyze_sentiment(self, posts: List[XPost]) -> XSentimentSummary:
        """Analyze sentiment of collected posts."""
        summary = XSentimentSummary()
        summary.total_posts = len(posts)

        if not posts:
            return summary

        scores = []
        for post in posts:
            score = self._score_post_sentiment(post)
            post.sentiment_score = score

            if score > 0.1:
                post.sentiment = "bullish"
                summary.bullish_count += 1
            elif score < -0.1:
                post.sentiment = "bearish"
                summary.bearish_count += 1
            else:
                post.sentiment = "neutral"
                summary.neutral_count += 1

            scores.append(score)

            # Detect whale alerts
            if post.username.lower() == "whale_alert" or "whale" in post.text.lower():
                summary.whale_alerts.append(
                    f"@{post.username}: {post.text[:150]}"
                )

        summary.avg_sentiment_score = sum(scores) / len(scores) if scores else 0.0

        # Top posts by engagement
        sorted_posts = sorted(posts, key=lambda p: p.engagement, reverse=True)
        summary.top_posts = sorted_posts[:5]

        return summary

    def _score_post_sentiment(self, post: XPost) -> float:
        """Score a post's sentiment from -1.0 (bearish) to +1.0 (bullish)."""
        text_lower = post.text.lower()
        bullish_hits = sum(1 for kw in BULLISH_KEYWORDS if kw.lower() in text_lower)
        bearish_hits = sum(1 for kw in BEARISH_KEYWORDS if kw.lower() in text_lower)

        total_hits = bullish_hits + bearish_hits
        if total_hits == 0:
            return 0.0

        raw_score = (bullish_hits - bearish_hits) / total_hits

        # Weight by engagement (more engagement = more influence)
        engagement = post.engagement
        if engagement > 1000:
            raw_score *= 1.3
        elif engagement > 100:
            raw_score *= 1.1

        return max(-1.0, min(1.0, raw_score))

    def _is_btc_related(self, text: str) -> bool:
        """Check if text is BTC-related."""
        text_lower = text.lower()
        btc_terms = [
            "bitcoin", "btc", "#btc", "#bitcoin",
            "ビットコイン", "satoshi", "sats",
            "crypto", "whale", "liquidation",
        ]
        return any(term in text_lower for term in btc_terms)

    @staticmethod
    def _parse_number(text: str) -> int:
        """Parse number strings like '1.2K', '3.5M'."""
        text = text.strip().replace(",", "")
        if not text:
            return 0
        try:
            if text.upper().endswith("K"):
                return int(float(text[:-1]) * 1000)
            elif text.upper().endswith("M"):
                return int(float(text[:-1]) * 1000000)
            return int(float(text))
        except ValueError:
            return 0

    @staticmethod
    def _parse_timestamp(time_str: str) -> Optional[datetime]:
        """Parse various timestamp formats."""
        formats = [
            "%b %d, %Y · %I:%M %p %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%b %d, %Y · %I:%M %p",
            "%d %b %Y %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(time_str.strip(), fmt)
            except ValueError:
                continue
        return None

    def get_status(self) -> Dict:
        """Get scraper status info."""
        with self._lock:
            cache_age = None
            if self._cache_time:
                cache_age = (
                    datetime.now(timezone.utc) - self._cache_time
                ).total_seconds()

            return {
                "working_instance": self._working_instance,
                "monitored_accounts": len(self.accounts),
                "cache_valid": self._is_cache_valid(),
                "cache_age_seconds": cache_age,
                "cached_posts": self._cache.total_posts if self._cache else 0,
            }
