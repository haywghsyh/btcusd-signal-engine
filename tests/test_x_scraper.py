"""Tests for X (Twitter) scraper module."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.data.x_scraper import (
    XPost,
    XScraper,
    XSentimentSummary,
    BULLISH_KEYWORDS,
    BEARISH_KEYWORDS,
)


class TestXPost:
    def test_post_id_unique(self):
        p1 = XPost(username="user1", text="bitcoin is pumping")
        p2 = XPost(username="user1", text="bitcoin is pumping")
        p3 = XPost(username="user2", text="bitcoin is pumping")
        assert p1.post_id == p2.post_id
        assert p1.post_id != p3.post_id

    def test_engagement(self):
        post = XPost(username="u", text="test", likes=100, retweets=50, replies=25)
        assert post.engagement == 175

    def test_engagement_zero(self):
        post = XPost(username="u", text="test")
        assert post.engagement == 0


class TestXSentimentSummary:
    def test_sentiment_label_bullish(self):
        s = XSentimentSummary(total_posts=10, avg_sentiment_score=0.3)
        assert "強気" in s.sentiment_label

    def test_sentiment_label_bearish(self):
        s = XSentimentSummary(total_posts=10, avg_sentiment_score=-0.3)
        assert "弱気" in s.sentiment_label

    def test_sentiment_label_neutral(self):
        s = XSentimentSummary(total_posts=10, avg_sentiment_score=0.05)
        assert "中立" in s.sentiment_label

    def test_sentiment_label_no_data(self):
        s = XSentimentSummary()
        assert "データなし" in s.sentiment_label

    def test_ratios(self):
        s = XSentimentSummary(
            total_posts=10, bullish_count=5, bearish_count=3, neutral_count=2
        )
        assert s.bullish_ratio == 0.5
        assert s.bearish_ratio == 0.3

    def test_ratios_zero(self):
        s = XSentimentSummary()
        assert s.bullish_ratio == 0.0
        assert s.bearish_ratio == 0.0

    def test_to_ai_summary_no_data(self):
        s = XSentimentSummary()
        result = s.to_ai_summary()
        assert "取得なし" in result

    def test_to_ai_summary_with_data(self):
        posts = [
            XPost(username="whale_alert", text="BTC whale moved 1000 BTC",
                  likes=500, retweets=200),
        ]
        s = XSentimentSummary(
            total_posts=10,
            bullish_count=6,
            bearish_count=2,
            neutral_count=2,
            avg_sentiment_score=0.4,
            top_posts=posts,
            whale_alerts=["@whale_alert: BTC whale moved 1000 BTC"],
        )
        result = s.to_ai_summary()
        assert "センチメント" in result
        assert "クジラ" in result
        assert "注目投稿" in result


class TestXScraperSentimentScoring:
    def setup_method(self):
        self.scraper = XScraper(cache_ttl_seconds=0)

    def test_bullish_post_scoring(self):
        post = XPost(username="u", text="Bitcoin is bullish! Rally incoming, buy now!")
        score = self.scraper._score_post_sentiment(post)
        assert score > 0

    def test_bearish_post_scoring(self):
        post = XPost(username="u", text="Bitcoin crash incoming, sell everything, panic!")
        score = self.scraper._score_post_sentiment(post)
        assert score < 0

    def test_neutral_post_scoring(self):
        post = XPost(username="u", text="Bitcoin price is 95000 today")
        score = self.scraper._score_post_sentiment(post)
        assert score == 0.0

    def test_high_engagement_amplifies_score(self):
        post_low = XPost(username="u", text="Bitcoin bullish rally", likes=5)
        post_high = XPost(
            username="u", text="Bitcoin bullish rally",
            likes=5000, retweets=2000,
        )
        score_low = self.scraper._score_post_sentiment(post_low)
        score_high = self.scraper._score_post_sentiment(post_high)
        assert abs(score_high) >= abs(score_low)

    def test_score_bounded(self):
        post = XPost(
            username="u",
            text=" ".join(BULLISH_KEYWORDS),
            likes=100000,
        )
        score = self.scraper._score_post_sentiment(post)
        assert -1.0 <= score <= 1.0


class TestXScraperBtcFilter:
    def setup_method(self):
        self.scraper = XScraper()

    def test_btc_related_true(self):
        assert self.scraper._is_btc_related("Bitcoin is pumping today")
        assert self.scraper._is_btc_related("BTC whale alert!")
        assert self.scraper._is_btc_related("#bitcoin #crypto")
        assert self.scraper._is_btc_related("ビットコイン速報")

    def test_btc_related_false(self):
        assert not self.scraper._is_btc_related("Ethereum is great")
        assert not self.scraper._is_btc_related("Nice weather today")


class TestXScraperParseNumber:
    def test_plain_number(self):
        assert XScraper._parse_number("1234") == 1234

    def test_k_suffix(self):
        assert XScraper._parse_number("1.5K") == 1500

    def test_m_suffix(self):
        assert XScraper._parse_number("2.3M") == 2300000

    def test_comma_separated(self):
        assert XScraper._parse_number("1,234") == 1234

    def test_empty(self):
        assert XScraper._parse_number("") == 0

    def test_invalid(self):
        assert XScraper._parse_number("abc") == 0


class TestXScraperAnalyzeSentiment:
    def setup_method(self):
        self.scraper = XScraper()

    def test_empty_posts(self):
        result = self.scraper._analyze_sentiment([])
        assert result.total_posts == 0
        assert result.avg_sentiment_score == 0.0

    def test_mixed_posts(self):
        posts = [
            XPost(username="u1", text="Bitcoin bullish pump rally!"),
            XPost(username="u2", text="Bitcoin crash dump sell!"),
            XPost(username="u3", text="BTC price is 95000"),
        ]
        result = self.scraper._analyze_sentiment(posts)
        assert result.total_posts == 3
        assert result.bullish_count >= 1
        assert result.bearish_count >= 1

    def test_whale_alert_detection(self):
        posts = [
            XPost(username="whale_alert", text="BTC 1000 BTC transferred"),
            XPost(username="user", text="Bitcoin whale moved coins"),
        ]
        result = self.scraper._analyze_sentiment(posts)
        assert len(result.whale_alerts) == 2


class TestXScraperCache:
    def test_cache_returns_cached_result(self):
        scraper = XScraper(cache_ttl_seconds=300)
        cached = XSentimentSummary(total_posts=5, avg_sentiment_score=0.2)
        scraper._cache = cached
        scraper._cache_time = datetime.now(timezone.utc)

        result = scraper.get_sentiment()
        assert result.total_posts == 5

    def test_get_status(self):
        scraper = XScraper()
        status = scraper.get_status()
        assert "monitored_accounts" in status
        assert "cache_valid" in status
        assert status["cache_valid"] is False


class TestXScraperCollect:
    @patch.object(XScraper, "_collect_posts")
    def test_get_sentiment_calls_collect(self, mock_collect):
        mock_collect.return_value = [
            XPost(username="u1", text="Bitcoin bullish pump!"),
        ]
        scraper = XScraper(cache_ttl_seconds=0)
        result = scraper.get_sentiment()
        assert result.total_posts == 1
        mock_collect.assert_called_once()

    @patch.object(XScraper, "_collect_posts")
    def test_get_sentiment_error_returns_empty(self, mock_collect):
        mock_collect.side_effect = Exception("Network error")
        scraper = XScraper(cache_ttl_seconds=0)
        result = scraper.get_sentiment()
        assert result.total_posts == 0

    @patch.object(XScraper, "_collect_posts")
    def test_get_sentiment_error_returns_stale_cache(self, mock_collect):
        scraper = XScraper(cache_ttl_seconds=0)
        scraper._cache = XSentimentSummary(total_posts=5)
        scraper._cache_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

        mock_collect.side_effect = Exception("Network error")
        result = scraper.get_sentiment()
        assert result.total_posts == 5  # Returns stale cache
