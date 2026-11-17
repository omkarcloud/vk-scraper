"""Offline tests for the VK exit tiers (vk/fetch.py): the pod's own IP, the
gateway exit for the hold after a block, a datacenter exit as the last retry
of a call the gateway also failed (2026-11-11). No network:
egress.new_session is replaced by scripted sessions.

    python -m pytest vk/test_fetch.py -q
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vk import fetch as F  # noqa: E402
from scraper_utils.testing import hosted_only

DC = "http://user:pw@dc.example:823"
RU = "http://user__cr.ru:pw@res.example:823"


class Resp:
    def __init__(self, status=200, body=None, url="https://web.api.vk.ru/method/users.get"):
        self.status_code, self.url = status, url
        self.text = body if isinstance(body, str) else json.dumps({"response": [{"id": 1}]} if body is None else body)

    def json(self):
        return json.loads(self.text)


TOKEN = Resp(body={"type": "okay", "data": {"access_token": "anonym.t", "expired_at": time.time() + 86400}})
RATE = Resp(body={"error": {"error_code": 29, "error_msg": "Rate limit reached"}})


class Sess:
    def __init__(self, exit_, responses):
        self.exit, self.responses, self.headers, self.closed = exit_, responses, {}, False

    def post(self, url, **kwargs):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def tiers(monkeypatch):
    """`tiers.script({exit: [response, ...]})`; `tiers.built` lists the exit
    of every session built. The anonymous token is already held."""
    monkeypatch.setattr(F.config, "VK_EXIT", "direct")
    monkeypatch.setattr(F.config, "VK_FALLBACK_EXIT", "gateway")
    monkeypatch.setattr(F.config, "VK_BLOCK_HOLD_S", 600)
    monkeypatch.setattr(F.config, "datacenter_proxy", lambda *a, **k: DC)
    monkeypatch.setattr(F.config, "residential_proxy", lambda *a, **k: RU)
    monkeypatch.setattr(F.config, "MAX_RETRIES", 3)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    monkeypatch.setitem(F._hold, "until", 0.0)
    monkeypatch.setitem(F._token, "value", "anonym.t")
    monkeypatch.setitem(F._token, "expires", time.time() + 86400)
    scripted, built = {}, []

    def new_session(exit_, impersonate="chrome", **kw):
        built.append(exit_)
        return Sess(exit_, scripted.setdefault(exit_, []))

    monkeypatch.setattr(F.egress, "new_session", new_session)
    F._local.__dict__.clear()
    F.script = lambda by_exit: scripted.update(by_exit)
    F.built = built
    yield F
    F._local.__dict__.clear()


@hosted_only
def test_block_tier_per_knob(tiers, monkeypatch):
    assert F.config.vk_proxy() is None
    assert F.config.vk_block_proxy() == "gateway" and F.config.vk_block_proxy(last=True) == DC
    monkeypatch.setattr(F.config, "VK_FALLBACK_EXIT", None)          # the pre-2026-11-11 tier
    assert F.config.vk_block_proxy() == DC
    monkeypatch.setattr(F.config, "VK_EXIT", "gateway")                  # the gateway as the default: datacenter next
    assert F.config.vk_proxy() == "gateway" and F.config.vk_block_proxy() == DC
    monkeypatch.setattr(F.config, "VK_EXIT", "datacenter")           # unchanged: RU residential next
    assert F.config.vk_proxy() == DC and F.config.vk_block_proxy() == RU


@hosted_only
def test_a_block_on_the_own_ip_moves_the_retry_and_new_sessions_to_the_gateway(tiers):
    F.script({None: [Resp(429, "slow down")], "gateway": [Resp(), Resp()]})
    assert F.fetch_user("durov") == [{"id": 1}]
    assert F.built == [None, "gateway"] and F._hold["until"] > time.time()
    assert F.fetch_user("id2") == [{"id": 1}] and F.built == [None, "gateway"]     # the thread's gateway session, reused


@hosted_only
def test_the_gateway_session_ends_with_the_hold(tiers):
    F.script({None: [RATE, Resp()], "gateway": [Resp()]})
    assert F.fetch_user("durov") == [{"id": 1}]
    F._hold["until"] = 0.0                                          # the hold ran out
    assert F.fetch_user("id2") == [{"id": 1}]
    assert F.built == [None, "gateway", None]


@hosted_only
def test_a_gateway_failure_degrades_to_a_datacenter_exit_on_the_last_retry(tiers):
    F.script({None: [Resp(403, "denied")], "gateway": [Resp(200, "<html>challenge.html?hash429</html>"), Resp()], DC: [Resp()]})
    assert F.fetch_user("durov") == [{"id": 1}]
    assert F.built == [None, "gateway", DC]
    assert F._local.session is None and not F._local.last_resort    # the datacenter session ended with the call
    assert F.fetch_user("id2") == [{"id": 1}] and F.built[-1] == "gateway"          # the hold: gateway first again


@hosted_only
def test_a_token_re_mint_inside_the_last_retry_keeps_the_datacenter_exit(tiers):
    """get_token() runs its own retry loop inside the call's attempt: it
    must not send the call's last retry back to the gateway."""
    F._hold["until"] = time.time() + 600
    refused = Resp(body={"error": {"error_code": 5, "error_msg": "User authorization failed"}})
    F.script({"gateway": [Resp(502, "bad gateway"), refused], DC: [TOKEN, Resp()]})
    assert F.fetch_user("durov") == [{"id": 1}]
    assert F.built == ["gateway", "gateway", DC]                            # the mint and the call share the datacenter session
    assert not F._local.last_resort


@hosted_only
def test_a_call_every_tier_fails_ends_after_three_attempts(tiers):
    F.script({None: [Resp(429)], "gateway": [Resp(429)], DC: [Resp(429)]})
    with pytest.raises(F.VkBlocked):
        F.fetch_user("durov")
    assert F.built == [None, "gateway", DC] and not F._local.last_resort


@hosted_only
def test_with_a_datacenter_block_tier_no_last_resort(tiers, monkeypatch):
    monkeypatch.setattr(F.config, "VK_FALLBACK_EXIT", "datacenter")
    F.script({None: [Resp(429)], DC: [Resp(429), Resp()]})
    assert F.fetch_user("durov") == [{"id": 1}]
    assert F.built == [None, DC, DC]
